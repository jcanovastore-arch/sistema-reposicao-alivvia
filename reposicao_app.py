# reposicao_app.py
# Reposição Logística — Alivvia (V8.6 - Raio-X Diagnóstico)

import os
import shutil
import datetime as dt
import pandas as pd
import streamlit as st
import io
import time

# Imports internos
from src.config import DEFAULT_SHEET_LINK, LOCAL_PADRAO_FILENAME
from src.utils import style_df_compra, norm_sku
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets
from src.logic import Catalogo, mapear_tipo, mapear_colunas, calcular
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# Login Simplificado
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

def check_password():
    if st.session_state.password_correct: return True
    # Senha padrão ou vazia para facilitar debug se necessário, ajuste conforme sua security
    pwd = st.text_input("Senha:", type="password")
    if pwd == st.secrets["access"]["password"]:
        st.session_state.password_correct = True
        st.rerun()
    return False

if not check_password(): st.stop()

# Inicialização de Estado
def _ensure_state():
    defaults = {
        "catalogo_df": None, "kits_df": None, "resultado_ALIVVIA": None, "resultado_JCA": None,
        "sel_A": {}, "sel_J": {}, "current_skus_A": [], "current_skus_J": [],
        "pedido_ativo": {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}
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

# Layout Principal
st.title("Reposição Logística — Alivvia (V8.6)")

if st.session_state.catalogo_df is None:
    st.warning("⚠️ Carregue o Padrão no menu lateral.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📂 Dados", "🔍 Análise", "📝 Editor", "🗂️ Gestão", "📦 Alocação"])

with tab1:
    c1, c2 = st.columns(2)
    def upload_card(emp, col):
        with col:
            st.subheader(emp)
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
                    st.info(f"Arquivo: {curr['name']}")

    upload_card("ALIVVIA", c1)
    upload_card("JCA", c2)
    
    # --- FERRAMENTA DE RAIO-X (DIAGNÓSTICO) ---
    st.divider()
    st.subheader("🕵️‍♂️ Raio-X do SKU (Diagnóstico)")
    sku_debug = st.text_input("Digite um SKU para investigar (Ex: MINIBAND):", value="MINIBAND").upper().strip()
    
    if sku_debug:
        col_debug1, col_debug2 = st.columns(2)
        
        def mostrar_raio_x(emp, col):
            with col:
                st.markdown(f"**{emp}**")
                # 1. Verifica no arquivo Bruto
                d_est = st.session_state[emp]["ESTOQUE"]
                raw_estoque = "N/A"
                raw_cols = []
                
                if d_est["bytes"]:
                    try:
                        df_raw = load_any_table_from_bytes(d_est["name"], d_est["bytes"])
                        raw_cols = list(df_raw.columns)
                        # Busca simples no bruto
                        mask = df_raw.astype(str).apply(lambda x: x.str.contains(sku_debug, case=False)).any(axis=1)
                        df_filt = df_raw[mask]
                        if not df_filt.empty:
                            st.write("🔎 Encontrado no CSV Bruto:")
                            st.dataframe(df_filt)
                            # Tenta achar a coluna de estoque
                            for c in df_filt.columns:
                                if "estoque" in c.lower() and "atual" in c.lower():
                                    raw_estoque = df_filt.iloc[0][c]
                        else:
                            st.warning("❌ SKU não encontrado no CSV Bruto.")
                    except: pass
                
                st.caption(f"Valor no Arquivo: {raw_estoque}")
                
                # 2. Verifica no DataFrame Calculado
                res = st.session_state.get(f"resultado_{emp}")
                if res is not None:
                    row = res[res["SKU"] == sku_debug]
                    if not row.empty:
                        st.write("📊 Resultado Calculado (Final):")
                        st.json({
                            "Estoque_Fisico_Final": int(row.iloc[0]["Estoque_Fisico"]),
                            "Vendas_60d": int(row.iloc[0]["Vendas_Total_60d"]),
                            "Reserva_30d (Subtraída?)": int(row.iloc[0]["Reserva_30d"]),
                            "Folga_Calculada": int(row.iloc[0]["Folga_Fisico"]),
                            "Compra_Sugerida": int(row.iloc[0]["Compra_Sugerida"])
                        })
                        
                        fis = int(row.iloc[0]["Estoque_Fisico"])
                        reserva = int(row.iloc[0]["Reserva_30d"])
                        diff = fis - reserva
                        st.info(f"Matemática: {fis} (Físico) - {reserva} (Reserva) = {diff}")
                        if diff == 304 or diff == 258:
                            st.error("ACHAMOS! Você está vendo a 'Folga' e não o Estoque Bruto.")
                    else:
                        st.warning("SKU sumiu após o cálculo (filtro de catálogo?).")

        mostrar_raio_x("ALIVVIA", col_debug1)
        mostrar_raio_x("JCA", col_debug2)

with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        def processar(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]):
                st.warning("Faltam arquivos Full ou Vendas."); return
            
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
                
                h = st.sidebar.selectbox("Horizonte", [60, 30, 90], index=0)
                res, _ = calcular(full_df, fis_df, vend_df, cat, h=h)
                st.session_state[f"resultado_{emp}"] = res
                st.success("Calculado!")
            except Exception as e:
                st.error(f"Erro no cálculo: {e}")

        if c1.button("Processar ALIVVIA"): processar("ALIVVIA")
        if c2.button("Processar JCA"): processar("JCA")
        
        # Tabelas
        for emp in ["ALIVVIA", "JCA"]:
            res = st.session_state.get(f"resultado_{emp}")
            if res is not None:
                st.subheader(f"Resultado {emp}")
                
                # --- TRUQUE DE EXIBIÇÃO ---
                # Garante que o usuário veja colunas claras
                df_show = res.copy()
                df_show = df_show.rename(columns={
                    "Estoque_Fisico": "Estoque Físico (BRUTO)",
                    "Folga_Fisico": "Estoque Livre (S/ Reserva)"
                })
                st.dataframe(df_show, use_container_width=True)

# Sidebar
with st.sidebar:
    if st.button("Carregar Padrão"):
        try:
            c, _ = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("Padrão Carregado!")
        except Exception as e: st.error(str(e))