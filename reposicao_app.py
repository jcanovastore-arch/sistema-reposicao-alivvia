# reposicao_app.py
# VERSÃO RESTAURADA: UI Completa (Sidebar, Filtros, Balanço) + Correção Lógica

import os
import datetime as dt
import pandas as pd
import streamlit as st
import numpy as np
import time

# Imports internos
from src.config import DEFAULT_SHEET_LINK
from src.utils import style_df_compra, norm_sku
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets
from src.logic import Catalogo, mapear_tipo, mapear_colunas, calcular

# ===================== CONFIGURAÇÃO =====================
st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== LOGIN =====================
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def check_password():
    if st.session_state.password_correct: return True
    pwd = st.text_input("🔒 Senha de Acesso:", type="password")
    if pwd == st.secrets["access"]["password"]:
        st.session_state.password_correct = True
        st.rerun()
    return False

if not check_password(): st.stop()

# ===================== ESTADO =====================
def _ensure_state():
    defaults = {
        "catalogo_df": None, "kits_df": None, 
        "resultado_ALIVVIA": None, "resultado_JCA": None,
        "sel_A": {}, "sel_J": {}, "current_skus_A": [], "current_skus_J": [],
        "pedido_ativo": {"itens": [], "fornecedor": None}
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

    for emp in ["ALIVVIA", "JCA"]:
        if emp not in st.session_state: st.session_state[emp] = {}
        for ft in ["FULL", "VENDAS", "ESTOQUE"]:
            if ft not in st.session_state[emp]:
                st.session_state[emp][ft] = {"name": None, "bytes": None}
            if not st.session_state[emp][ft]["name"]:
                p_bin = get_local_file_path(emp, ft)
                p_nam = get_local_name_path(emp, ft)
                if os.path.exists(p_bin) and os.path.exists(p_nam):
                    try:
                        with open(p_bin, 'rb') as f: st.session_state[emp][ft]["bytes"] = f.read()
                        with open(p_nam, 'r') as f: st.session_state[emp][ft]["name"] = f.read().strip()
                    except: pass

_ensure_state()

# ===================== AUXILIARES UI =====================
def reset_selection():
    st.session_state.sel_A = {}
    st.session_state.sel_J = {}

def callback_update_selection(key_widget, key_skus, sel_dict):
    if key_widget not in st.session_state: return
    changes = st.session_state[key_widget]["edited_rows"]
    current_skus = st.session_state[key_skus]
    for idx, change in changes.items():
        if "Selecionar" in change:
            if idx < len(current_skus):
                sku_clicado = current_skus[idx]
                sel_dict[sku_clicado] = change["Selecionar"]

# ===================== SIDEBAR =====================
with st.sidebar:
    st.header("⚙️ Parâmetros")
    h_param = st.selectbox("Horizonte (Dias)", [30, 60, 90], index=1)
    g_param = st.number_input("Crescimento (% a.m.)", value=0.0, step=0.5)
    lt_param = st.number_input("Lead Time (Dias)", value=0, step=1)
    
    st.markdown("---")
    st.subheader("Catálogo")
    if st.button("🔄 Carregar Padrão (Sheets)", use_container_width=True):
        try:
            c, _ = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("Padrão Atualizado!")
        except Exception as e: st.error(str(e))

# ===================== APP PRINCIPAL =====================
st.title("Reposição Logística — Alivvia (V8.8)")

if st.session_state.catalogo_df is None:
    st.warning("⚠️ Carregue o **Padrão** no menu lateral.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📂 Dados", "🔍 Análise", "📝 Editor", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS ---
with tab1:
    c1, c2 = st.columns(2)
    def upload_card(emp, col):
        with col:
            st.subheader(f"Dados: {emp}")
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                f = st.file_uploader(f"{ft}", key=f"u_{emp}_{ft}")
                if f:
                    p_bin = get_local_file_path(emp, ft)
                    p_nam = get_local_name_path(emp, ft)
                    with open(p_bin, 'wb') as fb: fb.write(f.read())
                    with open(p_nam, 'w') as fn: fn.write(f.name)
                    st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue()}
                    st.success("Salvo!")
                
                curr = st.session_state[emp][ft]
                if curr["name"]:
                    st.caption(f"✅ {curr['name']}")

    upload_card("ALIVVIA", c1)
    upload_card("JCA", c2)

# --- TAB 2: ANÁLISE ---
with tab2:
    if st.session_state.catalogo_df is not None:
        st.write("### Painel de Cálculo")
        c1, c2 = st.columns(2)
        
        def processar(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]):
                st.warning(f"{emp}: Faltam arquivos."); return
            
            try:
                full_raw = load_any_table_from_bytes(s["FULL"]["name"], s["FULL"]["bytes"])
                vend_raw = load_any_table_from_bytes(s["VENDAS"]["name"], s["VENDAS"]["bytes"])
                fis_raw  = pd.DataFrame()
                if s["ESTOQUE"]["bytes"]:
                    fis_raw = load_any_table_from_bytes(s["ESTOQUE"]["name"], s["ESTOQUE"]["bytes"])

                full_df = mapear_colunas(full_raw, "FULL")
                vend_df = mapear_colunas(vend_raw, "VENDAS")
                fis_df = pd.DataFrame()
                if not fis_raw.empty:
                    fis_df = mapear_colunas(fis_raw, "FISICO")
                
                cat = Catalogo(st.session_state.catalogo_df.rename(columns={"sku":"component_sku"}), st.session_state.kits_df)
                res, _ = calcular(full_df, fis_df, vend_df, cat, h=h_param, g=g_param, LT=lt_param)
                
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} Calculado!")
            except Exception as e: st.error(f"Erro: {e}")

        if c1.button("▶️ Calcular ALIVVIA", use_container_width=True): processar("ALIVVIA")
        if c2.button("▶️ Calcular JCA", use_container_width=True): processar("JCA")
        
        st.divider()
        
        # --- FILTROS GLOBAIS ---
        fc1, fc2 = st.columns(2)
        sku_filt = fc1.text_input("🔎 Filtro SKU", key="f_sku", on_change=reset_selection).upper().strip()
        
        # Coleta fornecedores
        all_forns = set()
        if st.session_state.resultado_ALIVVIA is not None: all_forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].unique())
        if st.session_state.resultado_JCA is not None: all_forns.update(st.session_state.resultado_JCA["fornecedor"].unique())
        forn_opts = ["TODOS"] + sorted(list(all_forns))
        forn_filt = fc2.selectbox("🏭 Fornecedor", forn_opts, key="f_forn", on_change=reset_selection)

        # --- BALANÇO E TABELA ---
        for emp in ["ALIVVIA", "JCA"]:
            res = st.session_state.get(f"resultado_{emp}")
            if res is not None:
                st.markdown(f"### 📊 Resultado: {emp}")
                
                # Aplica Filtros
                df_view = res.copy()
                if sku_filt: df_view = df_view[df_view["SKU"].str.contains(sku_filt, na=False)]
                if forn_filt != "TODOS": df_view = df_view[df_view["fornecedor"] == forn_filt]
                
                # Métricas de Balanço (Restauradas)
                m1, m2, m3, m4 = st.columns(4)
                tot_fis = int(df_view["Estoque_Fisico"].sum())
                val_fis = (df_view["Estoque_Fisico"] * df_view["Preco"]).sum()
                tot_full = int(df_view["Estoque_Full"].sum())
                val_full = (df_view["Estoque_Full"] * df_view["Preco"]).sum() # Estimativa usando preço custo

                m1.metric("Físico (UN)", f"{tot_fis:,}".replace(",", "."))
                m2.metric("Físico (R$)", f"R$ {val_fis:,.2f}")
                m3.metric("Full (UN)", f"{tot_full:,}".replace(",", "."))
                m4.metric("Full (R$)", f"R$ {val_full:,.2f}")
                
                # Tabela
                key_skus = f"current_skus_{emp}"
                sel_dict = st.session_state[f"sel_{emp[0]}"]
                
                # Garante unicidade visual
                df_view = df_view.drop_duplicates(subset=["SKU"]).reset_index(drop=True)
                st.session_state[key_skus] = df_view["SKU"].tolist()
                
                df_view.insert(0, "Selecionar", df_view["SKU"].map(lambda s: sel_dict.get(s, False)))
                
                cols_view = ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"]
                
                st.data_editor(
                    style_df_compra(df_view[cols_view]),
                    key=f"edit_{emp}",
                    column_config={"Selecionar": st.column_config.CheckboxColumn(default=False)},
                    use_container_width=True,
                    hide_index=True,
                    on_change=callback_update_selection,
                    args=(f"edit_{emp}", key_skus, sel_dict)
                )

# --- OUTRAS ABAS ---
with tab3: st.info("Editor de OC")
with tab4: st.info("Gestão")
with tab5: st.info("Alocação")