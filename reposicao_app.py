import os
import pandas as pd
import streamlit as st
import time
import datetime as dt
import pdfplumber # Necessário para ler PDF
import re # Necessário para ler PDF
import io # Necessário para ler PDF
import numpy as np # Necessário para lógica dos kits
from typing import Optional, Tuple

# Imports internos
from src.config import DEFAULT_SHEET_LINK
# format_br_int é necessário para formatar os valores inteiros corretamente
from src.utils import style_df_compra, norm_sku, format_br_currency, format_br_int 
# _carregar_padrao_de_content é necessária para o upload manual de planilha
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets, _carregar_padrao_de_content
# ESSENCIAL: Inclusão das funções de Kit que estavam causando o NameError
from src.logic import Catalogo, mapear_colunas, calcular, explodir_por_kits, construir_kits_efetivo
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== FUNÇÃO DE LEITURA PDF (CORRIGIDA) =====================
def extrair_dados_pdf_ml(pdf_bytes):
    """
    Lê o PDF de envio do ML usando extração de TABELA para evitar confundir
    EAN/Código de Barras com a Quantidade.
    """
    data = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tabela = page.extract_table()
                if tabela:
                    for row in tabela:
                        if not row or len(row) < 2: continue
                        col_produto = str(row[0])
                        col_qtd = str(row[1])
                        
                        match_sku = re.search(r'SKU:?\s*([\w\-\/]+)', col_produto, re.IGNORECASE)
                        qtd_limpa = re.sub(r'[^\d]', '', col_qtd)
                        
                        if match_sku and qtd_limpa:
                            sku = match_sku.group(1)
                            qty = int(qtd_limpa)
                            if qty < 100000: 
                                data.append({"SKU": norm_sku(sku), "Qtd_Envio": qty})
                else:
                    # Fallback para PDF sem tabela explícita (versão anterior)
                    text = page.extract_text()
                    if not text: continue
                    lines = text.split('\n')
                    for line in lines:
                        parts = line.split()
                        if len(parts) < 2: continue
                        match_sku_txt = re.search(r'SKU:?\s*([\w\-\/]+)', line, re.IGNORECASE)
                        if match_sku_txt:
                            sku_cand = match_sku_txt.group(1)
                            qtd_cand = 0
                            for p in reversed(parts):
                                p_clean = re.sub(r'[^\d]', '', p)
                                if p_clean.isdigit():
                                    val = int(p_clean)
                                    if 0 < val < 20000:
                                        qtd_cand = val
                                        break
                            if sku_cand and qtd_cand > 0:
                                data.append({"SKU": norm_sku(sku_cand), "Qtd_Envio": qtd_cand})

        return pd.DataFrame(data).drop_duplicates(subset=["SKU"])
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return pd.DataFrame()

# ===================== SEGURANÇA =====================
if "password_correct" not in st.session_state: st.session_state.password_correct = False
if not st.session_state.password_correct:
    pwd = st.text_input("🔒 Senha:", type="password")
    if pwd == st.secrets["access"]["password"]:
        st.session_state.password_correct = True
        st.rerun()
    st.stop()

# ===================== ESTADO E SETUP =====================
def _ensure_state():
    defaults = {"catalogo_df": None, "kits_df": None, "resultado_ALIVVIA": None, "resultado_JCA": None, "sel_A": {}, "sel_J": {}, "pedido_ativo": {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    for emp in ["ALIVVIA", "JCA"]:
        if emp not in st.session_state: st.session_state[emp] = {}
        for ft in ["FULL", "VENDAS", "ESTOQUE"]:
            if ft not in st.session_state[emp]: st.session_state[emp][ft] = {"name": None, "bytes": None}
            if not st.session_state[emp][ft]["name"]:
                try:
                    p = get_local_file_path(emp, ft)
                    n = get_local_name_path(emp, ft)
                    if os.path.exists(p):
                        with open(p, 'rb') as f: st.session_state[emp][ft]["bytes"] = f.read()
                        with open(n, 'r') as f: st.session_state[emp][ft]["name"] = f.read().strip()
                except: pass
_ensure_state()

# ===================== FUNÇÕES UI =====================
def reset_selection(): st.session_state.sel_A = {}; st.session_state.sel_J = {}
def update_sel(k_wid, k_sku, d_sel):
    if k_wid not in st.session_state: return
    chg = st.session_state[k_wid]["edited_rows"]
    skus = st.session_state[k_sku]
    for i, c in chg.items():
        if "Selecionar" in c and i < len(skus): d_sel[skus[i]] = c["Selecionar"]

def add_to_cart_full(df_source, emp):
    """Adiciona itens ao carrinho baseado na coluna 'Faltam_Comprar'"""
    if df_source is None or df_source.empty: return
    if "Faltam_Comprar" not in df_source.columns: return

    df_buy = df_source[df_source["Faltam_Comprar"] > 0].copy()
    if df_buy.empty: return st.toast("Nada faltante para comprar!", icon="✅")

    curr = st.session_state.pedido_ativo["itens"]
    curr_skus = [i["sku"] for i in curr]
    c = 0
    for _, r in df_buy.iterrows():
        if r["SKU"] not in curr_skus:
            preco = float(r["Preco"]) if "Preco" in r else 0.0
            curr.append({
                "sku": r["SKU"], 
                "qtd": int(r["Faltam_Comprar"]), 
                "valor_unit": preco, 
                "origem": f"FULL_{emp}"
            })
            c += 1
            
    st.session_state.pedido_ativo["itens"] = curr
    if not st.session_state.pedido_ativo["fornecedor"] and "fornecedor" in df_buy.columns:
         st.session_state.pedido_ativo["fornecedor"] = df_buy.iloc[0]["fornecedor"]
         
    st.toast(f"{c} itens adicionados ao pedido!", icon="🛒")

def add_to_cart(emp):
    sel = st.session_state[f"sel_{emp[0]}"]
    df = st.session_state[f"resultado_{emp}"]
    if df is None: return
    marcados = [k for k,v in sel.items() if v]
    if not marcados: return st.toast("Nada selecionado!")
    novos = df[df["SKU"].isin(marcados)]
    curr = st.session_state.pedido_ativo["itens"]
    curr_skus = [i["sku"] for i in curr]
    c = 0
    for _, r in novos.iterrows():
        if r["SKU"] not in curr_skus:
            curr.append({"sku": r["SKU"], "qtd": int(r.get("Compra_Sugerida", 0)), "valor_unit": float(r.get("Preco", 0)), "origem": emp})
            c += 1
    st.session_state.pedido_ativo["itens"] = curr
    st.toast(f"{c} itens adicionados!")
    
def clear_file_cache(empresa, tipo):
    file_path = get_local_file_path(empresa, tipo)
    name_path = get_local_name_path(empresa, tipo)
    if os.path.exists(file_path): os.remove(file_path)
    if os.path.exists(name_path): os.remove(name_path)
    st.session_state[empresa][tipo]["name"] = None
    st.session_state[empresa][tipo]["bytes"] = None
    st.rerun()

# ===================== SIDEBAR =====================
with st.sidebar:
    st.header("⚙️ Parâmetros")
    h_p = st.selectbox("Horizonte (Dias)", [30, 60, 90], index=1)
    g_p = st.number_input("Crescimento %", value=0.0, step=0.5)
    lt_p = st.number_input("Lead Time", value=0, step=1)
    st.divider()
    
    st.subheader("📂 Dados Mestre")
    # Opção 1: Google Sheets (Automático)
    if st.button("🔄 Baixar do Google Sheets"):
        try:
            c, origem = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success(f"Carregado via {origem}!")
        except Exception as e: 
            st.error(f"Erro ao conectar no Google: {e}"); st.warning("Use o upload manual abaixo.")

    # Opção 2: Upload Manual (Caso o Google falhe)
    up_manual = st.file_uploader("Ou carregue 'Padrao_produtos.xlsx' manual:", type=["xlsx"])
    if up_manual:
        try:
            from src.data import _carregar_padrao_de_content 
            c = _carregar_padrao_de_content(up_manual.getvalue())
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"sku":"component_sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("✅ Arquivo carregado manualmente!")
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

st.title("Reposição Logística — Alivvia")
if st.session_state.catalogo_df is None: st.warning("⚠️ Carregue o Padrão de Produtos no menu lateral.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📂 Uploads", "🔍 Análise & Compra", "🚛 Cruzar PDF Full", "📝 Editor OC", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS ---
with tab1:
    c1, c2 = st.columns(2)
    def up_block(emp, col):
        with col:
            st.subheader(emp)
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                curr = st.session_state[emp][ft]
                f = st.file_uploader(ft, key=f"u_{emp}_{ft}")
                if f:
                    with open(get_local_file_path(emp, ft), 'wb') as fb: fb.write(f.read())
                    with open(get_local_name_path(emp, ft), 'w') as fn: fn.write(f.name)
                    st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue()}
                    st.success("Salvo!")
                if curr["name"]:
                    col_n, col_b = st.columns([3, 1])
                    col_n.caption(f"✅ {curr['name']}")
                    if col_b.button("Limpar", key=f"cl_{emp}_{ft}"): clear_file_cache(emp, ft)
    up_block("ALIVVIA", c1); up_block("JCA", c2)

# --- TAB 2: ANÁLISE ---
with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        def run_calc(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]): return st.warning("Faltam arquivos (Full/Vendas).")
            try:
                full = mapear_colunas(load_any_table_from_bytes(s["FULL"]["name"], s["FULL"]["bytes"]), "FULL")
                vend = mapear_colunas(load_any_table_from_bytes(s["VENDAS"]["name"], s["VENDAS"]["bytes"]), "VENDAS")
                fis = pd.DataFrame()
                if s["ESTOQUE"]["bytes"]:
                    fis = mapear_colunas(load_any_table_from_bytes(s["ESTOQUE"]["name"], s["ESTOQUE"]["bytes"]), "FISICO")
                cat = Catalogo(st.session_state.catalogo_df.rename(columns={"sku":"component_sku"}), st.session_state.kits_df)
                res, _ = calcular(full, fis, vend, cat, h_p, g_p, lt_p)
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} OK!")
            except Exception as e: st.error(f"Erro: {e}")
        
        if c1.button("Calc ALIVVIA", use_container_width=True): run_calc("ALIVVIA")
        if c2.button("Calc JCA", use_container_width=True): run_calc("JCA")
        
        st.divider()

        # FILTROS (SKU e FORNECEDOR)
        f1, f2 = st.columns(2)
        sku_f = f1.text_input("🔎 Filtro SKU", key="f_sku", on_change=reset_selection).upper()
        
        forns = set()
        if st.session_state.resultado_ALIVVIA is not None: forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].dropna().unique())
        if st.session_state.resultado_JCA is not None: forns.update(st.session_state.resultado_JCA["fornecedor"].dropna().unique())
        lista_forns = ["TODOS"] + sorted(list(forns))
        forn_f = f2.selectbox("🏭 Filtro Fornecedor", lista_forns, key="f_forn", on_change=reset_selection)
        
        for emp in ["ALIVVIA", "JCA"]:
            if st.session_state.get(f"resultado_{emp}") is not None:
                st.markdown(f"### 📊 {emp}")
                df = st.session_state[f"resultado_{emp}"].copy()
                
                # APLICAÇÃO DOS FILTROS
                if sku_f: df = df[df["SKU"].str.contains(sku_f, na=False)]
                if forn_f != "TODOS": df = df[df["fornecedor"] == forn_f]
                
                # BALANÇO (Métricas de Unidade e Valor)
                if not df.empty and 'Estoque_Fisico' in df.columns and 'Estoque_Full' in df.columns and 'Preco' in df.columns:
                    m1, m2, m3, m4 = st.columns(4)
                    
                    # Converte para numérico antes de somar (garantia contra texto nos arquivos)
                    df['Preco'] = pd.to_numeric(df['Preco'], errors='coerce').fillna(0)
                    df['Estoque_Fisico'] = pd.to_numeric(df['Estoque_Fisico'], errors='coerce').fillna(0)
                    df['Estoque_Full'] = pd.to_numeric(df['Estoque_Full'], errors='coerce').fillna(0)

                    tot_fis = df['Estoque_Fisico'].sum()
                    tot_full = df['Estoque_Full'].sum()
                    val_fis = (df['Estoque_Fisico'] * df['Preco']).sum()
                    val_full = (df['Estoque_Full'] * df['Preco']).sum()

                    m1.metric("Físico (Un)", format_br_int(tot_fis))
                    m2.metric("Físico (R$)", format_br_currency(val_fis))
                    m3.metric("Full (Un)", format_br_int(tot_full))
                    m4.metric("Full (R$)", format_br_currency(val_full))
                
                # Tabela
                k_sku = f"c_skus_{emp}"
                st.session_state[k_sku] = df["SKU"].tolist()
                sel = st.session_state[f"sel_{emp[0]}"]
                df.insert(0, "Selecionar", df["SKU"].map(lambda x: sel.get(x, False)))
                
                cols = [c for c in ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"] if c in df.columns]
                st.data_editor(style_df_compra(df[cols]), key=f"ed_{emp}", use_container_width=True, hide_index=True, column_config={"Selecionar": st.column_config.CheckboxColumn(default=False)}, on_change=update_sel, args=(f"ed_{emp}", k_sku, sel))
                if st.button(f"🛒 Add ao Pedido ({emp})", key=f"bt_{emp}"): add_to_cart(emp)

# --- TAB 3: CRUZAMENTO PDF FULL (AGORA COM CUSTOS) ---
with tab3:
    st.header("🚛 Cruzar PDF de Envio vs Estoque Físico")
    st.info("O sistema agora separa os Kits e mostra os componentes (SKU simples) que faltam.")
    
    emp_pdf = st.radio("Empresa do Envio:", ["ALIVVIA", "JCA"], horizontal=True)
    pdf_file = st.file_uploader("Arrastar PDF do Envio Full", type=["pdf"])
    
    df_res = st.session_state.get(f"resultado_{emp_pdf}")
    
    if df_res is None:
        st.warning(f"⚠️ Primeiro vá na aba 'Análise & Compra' e clique em 'Calc {emp_pdf}' para carregar o Estoque Físico atual.")
    elif pdf_file:
        st.write("Lendo PDF e explodindo kits...")
        df_pdf = extrair_dados_pdf_ml(pdf_file.getvalue())
        
        if df_pdf.empty:
            st.error("Não consegui ler itens no PDF.")
        else:
            # ================= LÓGICA DE EXPLOSÃO =================
            if st.session_state.catalogo_df is None or st.session_state.kits_df is None:
                 st.error("Padrão de produtos não carregado. Não consigo explodir kits.")
            else:
                cat_obj = Catalogo(st.session_state.catalogo_df.rename(columns={"sku":"component_sku"}), st.session_state.kits_df)
                kits_validos = construir_kits_efetivo(cat_obj)
                
                # 2. Explode o PDF (Transforma 'Qtd_Envio' de Kits em 'Quantidade' de componentes)
                df_exploded = explodir_por_kits(df_pdf, kits_validos, "SKU", "Qtd_Envio")
                
                # Renomeia para clareza
                df_exploded = df_exploded.rename(columns={"Quantidade": "Qtd_Necessaria_Envio"})
                
                # 3. Cruzamento com Estoque Físico
                df_merged = df_exploded.merge(df_res[["SKU", "Estoque_Fisico", "fornecedor", "Preco"]], on="SKU", how="left")
                
                # Tratamento de Nulos
                df_merged["Estoque_Fisico"] = df_merged["Estoque_Fisico"].fillna(0).astype(int)
                df_merged["Preco"] = pd.to_numeric(df_merged["Preco"], errors='coerce').fillna(0.0)
                
                # Cálculo do que falta
                df_merged["Faltam_Comprar"] = (df_merged["Qtd_Necessaria_Envio"] - df_merged["Estoque_Fisico"]).clip(lower=0).astype(int)
                
                # CÁLCULOS DE CUSTO
                df_merged["Custo_Total_Envio"] = (df_merged["Qtd_Necessaria_Envio"] * df_merged["Preco"]).round(2)
                df_merged["Valor_Compra_Faltante"] = (df_merged["Faltam_Comprar"] * df_merged["Preco"]).round(2)
                
                st.write(f"### Resultado da Análise (Kits Explodidos: {len(df_pdf)} -> {len(df_merged)} itens)")
                
                # Métricas de custo
                total_full_cost = df_merged["Custo_Total_Envio"].sum()
                total_falta_cost = df_merged["Valor_Compra_Faltante"].sum()

                st.markdown("#### Análise de Custos")
                col_c1, col_c2, col_c3 = st.columns(3)

                col_c1.metric(
                    "Gasto Total para o Full", 
                    format_br_currency(total_full_cost),
                    help="Custo de reposição (Preço) de todas as peças necessárias para este envio."
                )

                col_c2.metric(
                    "Gasto Compra Faltante", 
                    format_br_currency(total_falta_cost),
                    help="Custo (Preço) da compra extra que você precisa fazer para atender este envio."
                )
                
                col_c3.metric(
                    "Itens Faltantes (Un)",
                    format_br_int(df_merged['Faltam_Comprar'].sum()),
                    help="Total de peças individuais que faltam no seu estoque físico para este envio."
                )
                
                # NOVA COR (Vermelho Escuro com Texto Branco)
                def highlight_falta(s):
                    return ['background-color: #8B0000; color: white' if v > 0 else '' for v in s]

                # Aplica a formatação de INTEIRO e mostra tabela
                cols_view = ["SKU", "Qtd_Necessaria_Envio", "Estoque_Fisico", "Faltam_Comprar", "Preco", "Valor_Compra_Faltante", "fornecedor"]
                
                # Mapeamento de formatação para remover os zeros e formatar moeda
                format_map = {
                    "Qtd_Necessaria_Envio": lambda x: format_br_int(x),
                    "Estoque_Fisico": lambda x: format_br_int(x),
                    "Faltam_Comprar": lambda x: format_br_int(x),
                    "Preco": lambda x: format_br_currency(x),
                    "Valor_Compra_Faltante": lambda x: format_br_currency(x),
                }

                st.dataframe(
                    df_merged[cols_view].style
                        .format(format_map)
                        .apply(highlight_falta, subset=["Faltam_Comprar"]),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Qtd_Necessaria_Envio": st.column_config.NumberColumn("Qtd P/ Enviar (Peças)", format="%d"),
                        "Faltam_Comprar": st.column_config.NumberColumn("🛑 Faltam Comprar", format="%d"),
                        "Preco": st.column_config.NumberColumn("Preço Unitário", format="R$ %.2f"),
                        "Valor_Compra_Faltante": st.column_config.NumberColumn("Valor Compra Faltante", format="R$ %.2f")
                    }
                )
                
                total_falta = df_merged["Faltam_Comprar"].sum()
                if total_falta > 0:
                    if st.button(f"🛒 Adicionar {int(total_falta)} peças faltantes ao Pedido", type="primary"):
                        add_to_cart_full(df_merged, emp_pdf)
                else:
                    st.balloons()
                    st.success("✅ Você tem estoque físico suficiente para este envio!")

# --- TAB 4: EDITOR ---
with tab4:
    st.header("📝 Editor de Ordem de Compra")
    ped = st.session_state.pedido_ativo
    c1, c2, c3 = st.columns(3)
    ped["fornecedor"] = c1.text_input("Fornecedor", ped["fornecedor"])
    ped["empresa"] = c2.selectbox("Empresa OC", ["ALIVVIA", "JCA"])
    ped["obs"] = c3.text_input("Obs", ped["obs"])
    
    if ped["itens"]:
        df_i = pd.DataFrame(ped["itens"])
        
        # Garante tipos e recalcula o total
        df_i["sku"] = df_i["sku"].apply(norm_sku)
        df_i["valor_unit"] = pd.to_numeric(df_i["valor_unit"], errors='coerce').fillna(0)
        df_i["qtd"] = pd.to_numeric(df_i["qtd"], errors='coerce').fillna(0).astype(int)
        df_i["Total"] = (df_i["qtd"] * df_i["valor_unit"]).round(2)
        
        # TENTA JUNTAR O NOME DO PRODUTO E FORNECEDOR (CONTEXTO CRUCIAL)
        if st.session_state.catalogo_df is not None:
             df_cat = st.session_state.catalogo_df.copy()
             
             # Renomeia colunas para o Join e Exibição
             df_cat = df_cat.rename(columns={"sku": "sku", "nome_produto": "Nome do Produto", "fornecedor": "Forn. Info"})
             
             # Limita colunas de catálogo para o Join
             cols_join = [c for c in ["sku", "Nome do Produto", "Forn. Info"] if c in df_cat.columns]
             
             # Faz o merge para adicionar as colunas de contexto
             df_i = df_i.merge(df_cat[cols_join], on="sku", how="left")
             
        # Colunas a exibir na ordem e nome desejados
        cols_display = ["sku", "Nome do Produto", "Forn. Info", "qtd", "valor_unit", "Total", "origem"]
        df_exibir = df_i[[c for c in cols_display if c in df_i.columns]].copy()

        # Configuração das colunas com formatação de moeda e número
        col_config = {
            "sku": st.column_config.TextColumn("SKU", disabled=True),
            "Nome do Produto": st.column_config.TextColumn("Produto", disabled=True), # Não editável
            "Forn. Info": st.column_config.TextColumn("Forn. Info", disabled=True), # Não editável
            "qtd": st.column_config.NumberColumn("Qtd", min_value=1, step=1, help="Quantidade a ser comprada", format="%d"),
            "valor_unit": st.column_config.NumberColumn("Preço Unitário (R$)", format="R$ %.2f", help="Valor de custo/compra por unidade"),
            "Total": st.column_config.NumberColumn("Total (R$)", format="R$ %.2f", disabled=True), # Não editável
            "origem": st.column_config.TextColumn("Origem", disabled=True)
        }
        
        ed = st.data_editor(
            df_exibir, 
            num_rows="dynamic", 
            use_container_width=True, 
            key="ed_oc",
            column_config=col_config,
            hide_index=True
        )
        
        # Recalcula o total com os dados editados
        tot = (ed["qtd"] * ed["valor_unit"]).sum()
        
        # Salva o resultado editado de volta no estado da sessão (salva só o essencial para o DB)
        st.session_state.pedido_ativo["itens"] = ed[["sku", "qtd", "valor_unit", "origem"]].rename(columns={"valor_unit": "valor_unit", "qtd": "qtd"}).to_dict("records")

        st.metric("Total Pedido", format_br_currency(tot))
        
        if st.button("💾 Salvar OC", type="primary"):
            nid = gerar_numero_oc(ped["empresa"])
            dados = {"id": nid, "empresa": ped["empresa"], "fornecedor": ped["fornecedor"], "data_emissao": dt.date.today().strftime("%Y-%m-%d"), "valor_total": float(tot), "status": "Pendente", "obs": ped["obs"], "itens": st.session_state.pedido_ativo["itens"]}
            if salvar_pedido(dados):
                st.success(f"OC {nid} gerada!"); st.session_state.pedido_ativo["itens"] = []; time.sleep(1); st.rerun()
        if st.button("🗑️ Limpar"): st.session_state.pedido_ativo["itens"] = []; st.rerun()
    else: st.info("Carrinho vazio.")
# --- TAB 5: GESTÃO ---
with tab5:
    st.header("🗂️ Gestão de OCs")
    if st.button("🔄 Atualizar"): st.rerun()
    df_ocs = listar_pedidos()
    if not df_ocs.empty:
        st.dataframe(df_ocs[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status"]], use_container_width=True, hide_index=True)
        sel_oc = st.selectbox("ID", df_ocs["ID"].unique())
        if sel_oc:
            row = df_ocs[df_ocs["ID"] == sel_oc].iloc[0]
            ns = st.selectbox("Status", ["Pendente", "Aprovado", "Enviado", "Recebido", "Cancelado"])
            if st.button("Atualizar Status"): atualizar_status(sel_oc, ns); st.rerun()
            if st.button("Excluir"): excluir_pedido_db(sel_oc); st.rerun()

# --- TAB 6: ALOCAÇÃO ---
with tab6:
    st.header("📦 Alocação de Compra")
    ra = st.session_state.get("resultado_ALIVVIA")
    rj = st.session_state.get("resultado_JCA")
    if ra is None or rj is None: st.info("Calcule ambas as empresas na aba 'Análise' primeiro.")
    else:
        try:
            cols_req = ["SKU", "Vendas_Total_60d", "Estoque_Fisico"]
            # Garante que as colunas existem antes de tentar acessar
            if not all(c in ra.columns for c in cols_req) or not all(c in rj.columns for c in cols_req):
                 st.error("Faltam colunas essenciais nos arquivos carregados para fazer a alocação.")
            else:
                df_A = ra[cols_req].rename(columns={"Vendas_Total_60d": "Vendas_A", "Estoque_Fisico": "Estoque_A"})
                df_J = rj[cols_req].rename(columns={"Vendas_Total_60d": "Vendas_J", "Estoque_Fisico": "Estoque_J"})
                base = pd.merge(df_A, df_J, on="SKU", how="outer").fillna(0)
                sku = st.selectbox("SKU:", ["Selecione"] + base["SKU"].unique().tolist())
                if sku != "Selecione":
                    r = base[base["SKU"] == sku].iloc[0]
                    c1,c2,c3 = st.columns(3)
                    c1.metric("Vendas A", format_br_int(r["Vendas_A"])); 
                    c2.metric("Vendas J", format_br_int(r["Vendas_J"])); 
                    c3.metric("Físico Total", format_br_int(r["Estoque_A"]+r["Estoque_J"]))
                    compra = st.number_input("Qtd Compra:", min_value=1, value=500)
                    tot_v = r["Vendas_A"] + r["Vendas_J"]
                    perc = (r["Vendas_A"]/tot_v) if tot_v > 0 else 0.5
                    st.info(f"Sugestão: {format_br_int(compra*perc)} Alivvia | {format_br_int(compra*(1-perc))} JCA")
        except Exception as e: 
            st.error(f"Erro ao cruzar dados para alocação: {e}")