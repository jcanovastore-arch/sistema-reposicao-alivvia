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
from src.config import DEFAULT_SHEET_LINK, STORAGE_DIR
# format_br_int é necessário para formatar os valores inteiros corretamente
from src.utils import style_df_compra, norm_sku, format_br_currency, format_br_int 
# _carregar_padrao_de_content é necessária para o upload manual de planilha
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets, _carregar_padrao_de_content
# ESSENCIAL: Inclusão das funções de Kit e cálculo
from src.logic import Catalogo, mapear_colunas, calcular, explodir_por_kits, construir_kits_efetivo
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== FUNÇÕES DE CAMINHO DE CACHE =====================
# É CRÍTICO que esta função exista para gerenciar o timestamp
def get_local_timestamp_path(empresa: str, tipo: str) -> str:
    """Retorna o caminho local para o arquivo de timestamp."""
    # Assume que STORAGE_DIR está definido em src.config
    return os.path.join(STORAGE_DIR, f"{empresa}_{tipo}_time.txt")


# ===================== FUNÇÃO DE LEITURA PDF =====================
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
                        # Garante que as colunas são strings para a regex
                        col_produto = str(row[0]) if len(row) > 0 and row[0] is not None else ""
                        col_qtd = str(row[1]) if len(row) > 1 and row[1] is not None else ""
                        
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
            # CRÍTICO: Atualiza o default para incluir 'timestamp'
            if ft not in st.session_state[emp] or "timestamp" not in st.session_state[emp][ft]: 
                st.session_state[emp][ft] = {"name": None, "bytes": None, "timestamp": None}
            
            # Tenta carregar cache local
            if not st.session_state[emp][ft]["name"]:
                try:
                    p = get_local_file_path(emp, ft)
                    n = get_local_name_path(emp, ft)
                    t = get_local_timestamp_path(emp, ft)
                    
                    if os.path.exists(p):
                        # Carrega bytes e nome
                        with open(p, 'rb') as f: st.session_state[emp][ft]["bytes"] = f.read()
                        with open(n, 'r') as f: st.session_state[emp][ft]["name"] = f.read().strip()
                        
                        # Carrega timestamp
                        if os.path.exists(t):
                             with open(t, 'r') as f: st.session_state[emp][ft]["timestamp"] = f.read().strip()
                        else:
                             # Fallback: USA A DATA DE MODIFICAÇÃO DO ARQUIVO .BIN
                             st.session_state[emp][ft]["timestamp"] = dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d/%m/%Y %H:%M:%S")

                except: 
                    st.session_state[emp][ft] = {"name": None, "bytes": None, "timestamp": None}
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

    # Filtra apenas o que falta para comprar
    df_buy = df_source[df_source["Faltam_Comprar"] > 0].copy()
    if df_buy.empty: return st.toast("Nada faltante para comprar!", icon="✅")

    curr = st.session_state.pedido_ativo["itens"]
    curr_skus = [i["sku"] for i in curr]
    c = 0
    for _, r in df_buy.iterrows():
        if r["SKU"] not in curr_skus:
            # Tenta pegar 'Preco' ou cai em 0.0 se não existir
            preco = float(r.get("Preco", 0.0))
            curr.append({
                "sku": r["SKU"], 
                "qtd": int(r["Faltam_Comprar"]), 
                "valor_unit": preco, 
                "origem": f"FULL_{emp}"
            })
            c += 1
            
    st.session_state.pedido_ativo["itens"] = curr
    # Tenta preencher fornecedor
    if not st.session_state.pedido_ativo["fornecedor"] and "fornecedor" in df_buy.columns and not df_buy["fornecedor"].empty:
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
        # Tentamos usar Compra_Sugerida, mas caímos em 0 se não houver
        qtd = int(r.get("Compra_Sugerida", 0))
        if r["SKU"] not in curr_skus and qtd > 0:
            curr.append({"sku": r["SKU"], "qtd": qtd, "valor_unit": float(r.get("Preco", 0)), "origem": emp})
            c += 1
    st.session_state.pedido_ativo["itens"] = curr
    if not st.session_state.pedido_ativo["fornecedor"] and not novos.empty:
        st.session_state.pedido_ativo["fornecedor"] = novos.iloc[0]["fornecedor"]
    st.toast(f"{c} itens adicionados!")
    
def clear_file_cache(empresa, tipo):
    """Remove o arquivo .bin, .txt e _time.txt do cache local"""
    file_path = get_local_file_path(empresa, tipo)
    name_path = get_local_name_path(empresa, tipo)
    time_path = get_local_timestamp_path(empresa, tipo) 
    
    deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        deleted = True
    if os.path.exists(name_path):
        os.remove(name_path)
        deleted = True
    if os.path.exists(time_path): 
        os.remove(time_path)
        
    # CRÍTICO: Resetar a sessão para forçar o recálculo
    st.session_state[empresa][tipo] = {"name": None, "bytes": None, "timestamp": None}
    st.session_state[f"resultado_{empresa}"] = None # Limpa o cálculo da Tab 2
    
    if deleted:
        st.toast(f"Cache de {empresa} {tipo} limpo!", icon="🧹")
        time.sleep(1)
        st.rerun()

def reset_master_data():
    st.session_state.catalogo_df = None
    st.session_state.kits_df = None
    st.toast("Dados Mestre (Catálogo e Kits) limpos! Recarregue-os.", icon="🧹")
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
            # CRÍTICO: Manter o nome 'component_sku' que logic.py espera.
            st.session_state.catalogo_df = c.catalogo_simples
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
            # CRÍTICO: Manter o nome 'component_sku' que logic.py espera.
            st.session_state.catalogo_df = c.catalogo_simples
            st.session_state.kits_df = c.kits_reais
            st.success("✅ Arquivo carregado manualmente!")
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

    st.divider()
    # NOVO BOTÃO DE LIMPEZA DO CATÁLOGO
    st.button("🧹 Limpar Dados Mestre (Catálogo/Kits)", type="secondary", on_click=reset_master_data)

st.title("Reposição Logística — Alivvia")
if st.session_state.catalogo_df is None: st.warning("⚠️ Carregue o Padrão de Produtos no menu lateral.")

# 🛑 LAYOUT DE 6 ABAS RESTAURADO
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📂 Uploads", "🔍 Análise & Compra", "🚛 Cruzar PDF Full", "📝 Editor OC", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS (CORRIGIDO PARA UNICIDADE E TIMESTAMP) ---
with tab1:
    st.subheader("⚠️ Arquivos Operacionais (Vendas, Estoque, Full)")
    st.info("Apenas o último arquivo carregado para cada tipo é mantido no cache local para garantir a unicidade dos dados.")
    
    c1, c2 = st.columns(2)
    def up_block(emp, col):
        with col:
            st.markdown(f"### {emp}")
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                curr_state = st.session_state[emp][ft]
                
                f = st.file_uploader(f"Upload {ft}", type=["xlsx", "csv", "pdf"], key=f"u_{emp}_{ft}")
                
                if f:
                    # Lógica de Sobrescrita e Timestamp
                    time_path = get_local_timestamp_path(emp, ft)
                    
                    # Usa a variável 'f' para obter o nome e conteúdo AGORA
                    file_bytes = f.getvalue()
                    file_name = f.name
                    timestamp_str = dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

                    # 1. Salva o conteúdo do arquivo (sobrescreve o .bin)
                    with open(get_local_file_path(emp, ft), 'wb') as fb: fb.write(file_bytes)
                    # 2. Salva o nome do arquivo (sobrescreve o .txt)
                    with open(get_local_name_path(emp, ft), 'w') as fn: fn.write(file_name)
                    # 3. Salva o timestamp (sobrescreve o _time.txt)
                    with open(time_path, 'w') as ft_w: ft_w.write(timestamp_str)
                    
                    # 4. Atualiza a sessão para o novo arquivo
                    st.session_state[emp][ft] = {"name": file_name, "bytes": file_bytes, "timestamp": timestamp_str}
                    st.toast("✅ Arquivo Salvo e Sobrescrito!")
                    
                    # 🛑 CRÍTICO: REMOVE st.rerun() e time.sleep(1) para evitar loop e piscadas
                    
                # A lógica de exibição está correta (agora que o flow control foi corrigido)
                if curr_state["name"]:
                    st.caption(f"**Nome:** {curr_state['name']}")
                    # CRÍTICO: O timestamp deve vir do estado da sessão
                    st.caption(f"**Data Upload:** {curr_state['timestamp'] if curr_state['timestamp'] else 'Carregado de Versão Antiga'}")
                    
                    if st.button("🧹 Limpar Cache", key=f"clean_{emp}_{ft}"):
                        clear_file_cache(emp, ft)

    up_block("ALIVVIA", c1); up_block("JCA", c2)

# --- TAB 2: ANÁLISE E COMPRA ---
with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        def run_calc(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]): return st.warning("Faltam arquivos.")
            try:
                full = mapear_colunas(load_any_table_from_bytes(s["FULL"]["name"], s["FULL"]["bytes"]), "FULL")
                vend = mapear_colunas(load_any_table_from_bytes(s["VENDAS"]["name"], s["VENDAS"]["bytes"]), "VENDAS")
                fis = pd.DataFrame()
                if s["ESTOQUE"]["bytes"]:
                    fis = mapear_colunas(load_any_table_from_bytes(s["ESTOQUE"]["name"], s["ESTOQUE"]["bytes"]), "FISICO")
                # CRÍTICO: Passamos o df do catálogo com a coluna 'component_sku' correta
                cat = Catalogo(st.session_state.catalogo_df, st.session_state.kits_df)
                res, _ = calcular(full, fis, vend, cat, h_p, g_p, lt_p)
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} OK!")
            except Exception as e: st.error(f"Erro: {e}")
        
        if c1.button("Calc ALIVVIA", use_container_width=True): run_calc("ALIVVIA")
        if c2.button("Calc JCA", use_container_width=True): run_calc("JCA")
        
        st.divider()

        # Filtros
        f1, f2 = st.columns(2)
        sku_f = f1.text_input("🔎 Filtro SKU", key="f_sku", on_change=reset_selection).upper()
        
        forns = set()
        if st.session_state.resultado_ALIVVIA is not None: forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].dropna().unique())
        if st.session_state.resultado_JCA is not None: forns.update(st.session_state.resultado_JCA["fornecedor"].dropna().unique())
        lista_forns = ["TODOS"] + sorted(list(forns))
        forn_f = f2.selectbox("🏭 Filtro Fornecedor", lista_forns, key="f_forn", on_change=reset_selection)
        
        for i, emp in enumerate(["ALIVVIA", "JCA"]):
            if st.session_state.get(f"resultado_{emp}") is not None:
                st.markdown(f"### 📊 {emp}")
                df = st.session_state[f"resultado_{emp}"].copy()
                
                if sku_f: df = df[df["SKU"].str.contains(sku_f, na=False)]
                if forn_f != "TODOS": df = df[df["fornecedor"] == forn_f]
                
                # Balanço
                if not df.empty:
                    m1, m2, m3, m4 = st.columns(4)
                    
                    # Converte para numérico antes de somar (garantia contra texto nos arquivos)
                    df['Preco'] = pd.to_numeric(df['Preco'], errors='coerce').fillna(0)
                    df['Estoque_Fisico'] = pd.to_numeric(df['Estoque_Fisico'], errors='coerce').fillna(0)
                    df['Estoque_Full'] = pd.to_numeric(df['Estoque_Full'], errors='coerce').fillna(0)
                    
                    tot_fis = df['Estoque_Fisico'].sum()
                    val_fis = (df['Estoque_Fisico'] * df['Preco']).sum()
                    tot_full = df['Estoque_Full'].sum()
                    val_full = (df['Estoque_Full'] * df['Preco']).sum()

                    m1.metric("Físico (Un)", format_br_int(tot_fis))
                    m2.metric("Físico (R$)", format_br_currency(val_fis))
                    m3.metric("Full (Un)", format_br_int(tot_full))
                    m4.metric("Full (R$)", format_br_currency(val_full))
                
                # Tabela
                k_sku = f"current_skus_{emp}"
                st.session_state[k_sku] = df["SKU"].tolist()
                sel = st.session_state[f"sel_{emp[0]}"]
                df.insert(0, "Selecionar", df["SKU"].map(lambda x: sel.get(x, False)))
                
                cols = ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"]
                
                st.data_editor(
                    style_df_compra(df[cols]), 
                    key=f"ed_{emp}", 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Selecionar": st.column_config.CheckboxColumn(default=False),
                        "Estoque_Fisico": st.column_config.NumberColumn("Físico (Bruto)", help="Estoque lido diretamente do arquivo.", format="%d"),
                        "Preco": st.column_config.NumberColumn("Preço Unitário", format="R$ %.2f"),
                        "Valor_Compra_R$": st.column_config.NumberColumn("Valor Compra", format="R$ %.2f")
                    },
                    on_change=update_sel, 
                    args=(f"ed_{emp}", k_sku, sel)
                )
                
                if st.button(f"🛒 Enviar Selecionados ({emp}) para Editor", key=f"bt_{emp}"): 
                    add_to_cart(emp)

# --- TAB 3: CRUZAR PDF FULL (CORRIGIDO COM EXPLOSÃO) ---
with tab3:
    st.header("🚛 Cruzar PDF Full")
    st.info("⚠️ Para análise correta, calcule a aba 'Análise & Compra' primeiro. O Catálogo de Kits e Preços será usado na explosão.")

    emp_pdf = st.radio("Empresa do Envio:", ["ALIVVIA", "JCA"], horizontal=True, key="emp_pdf_full")
    pdf_file = st.file_uploader("Upload PDF de Instruções de Preparação", type=["pdf"], key="pdf_full_upload_tab3")
    
    df_res = st.session_state.get(f"resultado_{emp_pdf}") # Estoque Físico e Preços vêm da Tab 2
    
    if df_res is None:
        st.warning(f"⚠️ Primeiro vá na aba 'Análise & Compra' e clique em 'Calc {emp_pdf}' para carregar o Estoque Físico e Preços atuais.")
    elif pdf_file:
        st.write("Lendo PDF e explodindo kits...")
        df_pdf_bruto = extrair_dados_pdf_ml(pdf_file.getvalue())
        
        if df_pdf_bruto.empty:
            st.error("Não consegui ler itens no PDF.")
        else:
            # ================= LÓGICA DE EXPLOSÃO =================
            if st.session_state.catalogo_df is None or st.session_state.kits_df is None:
                 st.error("Padrão de produtos não carregado. Não consigo explodir kits. Por favor, carregue na barra lateral.")
            else:
                # O catálogo já está armazenado com o nome de coluna CORRETO (component_sku)
                cat_obj = Catalogo(st.session_state.catalogo_df, st.session_state.kits_df)
                kits_validos = construir_kits_efetivo(cat_obj)
                
                # 2. Explode o PDF (Transforma 'Qtd_Envio' de Kits em 'Quantidade' de componentes)
                df_exploded = explodir_por_kits(df_pdf_bruto, kits_validos, "SKU", "Qtd_Envio")
                
                df_exploded = df_exploded.rename(columns={"Quantidade": "Qtd_Necessaria_Envio"})
                
                # 3. Cruzamento com Estoque Físico (df_res vem da Tab 2, com Preco e Estoque_Fisico)
                cols_to_merge = ["SKU", "Estoque_Fisico", "fornecedor", "Preco"]
                df_merged = df_exploded.merge(df_res[cols_to_merge], on="SKU", how="left")
                
                # Tratamento de Nulos e Tipos
                df_merged["Estoque_Fisico"] = df_merged["Estoque_Fisico"].fillna(0).astype(int)
                df_merged["Preco"] = pd.to_numeric(df_merged["Preco"], errors='coerce').fillna(0.0)
                df_merged["fornecedor"] = df_merged["fornecedor"].fillna("Não Cadastrado")
                
                # Cálculo do que falta (CRÍTICO: Objetivo da aba)
                df_merged["Faltam_Comprar"] = (df_merged["Qtd_Necessaria_Envio"] - df_merged["Estoque_Fisico"]).clip(lower=0).astype(int)
                
                # CÁLCULOS DE CUSTO (Exigidos pelo usuário)
                df_merged["Custo_Total_Envio"] = (df_merged["Qtd_Necessaria_Envio"] * df_merged["Preco"]).round(2)
                df_merged["Valor_Compra_Faltante"] = (df_merged["Faltam_Comprar"] * df_merged["Preco"]).round(2)
                
                st.write(f"### Resultado da Análise (Kits Explodidos: {len(df_pdf_bruto)} Kits -> {len(df_merged)} Componentes)")
                
                # Métricas de custo (Sempre aparecem agora)
                total_full_cost = df_merged["Custo_Total_Envio"].sum()
                total_falta_cost = df_merged["Valor_Compra_Faltante"].sum()

                st.markdown("#### Análise de Custos")
                col_c1, col_c2, col_c3 = st.columns(3)

                col_c1.metric(
                    "Gasto Total para o Full (R$)", 
                    format_br_currency(total_full_cost),
                    help="Custo de reposição (Preço) de todas as peças (componentes) necessárias para este envio."
                )

                col_c2.metric(
                    "Gasto Compra Faltante (R$)", 
                    format_br_currency(total_falta_cost),
                    help="Custo (Preço) da compra extra que você precisa fazer para atender este envio."
                )
                
                col_c3.metric(
                    "Itens Faltantes (Un)",
                    format_br_int(df_merged['Faltam_Comprar'].sum()),
                    help="Total de peças individuais que faltam no seu estoque físico para este envio."
                )
                
                # Tabela
                def highlight_falta(s):
                    return ['background-color: #8B0000; color: white' if v > 0 else '' for v in s]

                cols_view = ["SKU", "Qtd_Necessaria_Envio", "Estoque_Fisico", "Faltam_Comprar", "Preco", "Valor_Compra_Faltante", "fornecedor"]
                
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
                        "Estoque_Fisico": st.column_config.NumberColumn("Estoque Físico", format="%d"),
                        "Faltam_Comprar": st.column_config.NumberColumn("🛑 Faltam Comprar", format="%d"),
                        "Preco": st.column_config.NumberColumn("Preço Unitário", format="R$ %.2f"),
                        "Valor_Compra_Faltante": st.column_config.NumberColumn("Valor Compra Faltante", format="R$ %.2f")
                    }
                )
                
                total_falta = df_merged["Faltam_Comprar"].sum()
                if total_falta > 0:
                    if st.button(f"🛒 Adicionar {format_br_int(total_falta)} peças faltantes ao Pedido", type="primary"):
                        add_to_cart_full(df_merged, emp_pdf)
                else:
                    st.balloons()
                    st.success("✅ Você tem estoque físico suficiente para este envio!")

# --- TAB 4: EDITOR OC (CORRIGIDA PARA ADIÇÃO MANUAL) ---
with tab4:
    st.header("📝 Editor de Ordem de Compra")
    st.info("⚠️ Para adicionar um item manualmente, digite o SKU, Qtd e Preço Unitário na última linha da tabela.")
    ped = st.session_state.pedido_ativo
    c1, c2, c3 = st.columns(3)
    ped["fornecedor"] = c1.text_input("Fornecedor", ped["fornecedor"])
    ped["empresa"] = c2.selectbox("Empresa OC", ["ALIVVIA", "JCA"])
    ped["obs"] = c3.text_input("Obs", ped["obs"])
    
    # CRÍTICO: Cria um DataFrame vazio se o carrinho estiver vazio
    if ped["itens"]:
        df_i = pd.DataFrame(ped["itens"])
    else:
        # Cria um DataFrame vazio com as colunas necessárias para o JOIN e edição
        default_cols = ["sku", "qtd", "valor_unit", "origem"]
        df_i = pd.DataFrame([], columns=default_cols)
        # Define valores padrão para que o st.data_editor possa criar novas linhas
        df_i = df_i.astype({"sku": str, "qtd": int, "valor_unit": float, "origem": str})
    
    # Garante tipos e recalcula o total
    df_i["sku"] = df_i["sku"].apply(norm_sku)
    df_i["valor_unit"] = pd.to_numeric(df_i["valor_unit"], errors='coerce').fillna(0)
    df_i["qtd"] = pd.to_numeric(df_i["qtd"], errors='coerce').fillna(0).astype(int)
    df_i["Total"] = (df_i["qtd"] * df_i["valor_unit"]).round(2)
    
    # LÓGICA DE JOIN CRUCIAL: Traz Nome do Produto e Fornecedor (COM SEGURANÇA CONTRA KEYERROR)
    if st.session_state.catalogo_df is not None:
         df_cat = st.session_state.catalogo_df.copy()
         
         rename_map = {}
         # Tentamos renomear as colunas que esperamos. Se não existirem, elas não são renomeadas.
         if 'nome_produto' in df_cat.columns: rename_map['nome_produto'] = 'Nome do Produto'
         if 'fornecedor' in df_cat.columns: rename_map['fornecedor'] = 'Forn. Info'
         
         # CRÍTICO: O catálogo está com 'component_sku', renomeamos para 'sku' apenas para o merge aqui
         df_cat = df_cat.rename(columns={'component_sku': 'sku'})
         df_cat = df_cat.rename(columns=rename_map)

         # Colunas a serem usadas no merge: verificamos quais colunas de contexto estão presentes
         cols_to_merge = ["sku"]
         if "Nome do Produto" in df_cat.columns: cols_to_merge.append("Nome do Produto")
         if "Forn. Info" in df_cat.columns: cols_to_merge.append("Forn. Info")
         
         # Faz o merge para adicionar as colunas de contexto (df_i já pode ser um DataFrame vazio aqui)
         df_i = df_i.merge(df_cat[cols_to_merge], on="sku", how="left")
         
    # Colunas a exibir na ordem e nome desejados
    cols_display = ["sku", "Nome do Produto", "Forn. Info", "qtd", "valor_unit", "Total", "origem"]
    # Garante que só as colunas existentes sejam exibidas
    df_exibir = df_i[[c for c in cols_display if c in df_i.columns]].copy()

    # Configuração das colunas com formatação de moeda e número
    col_config = {
        "sku": st.column_config.TextColumn("SKU", disabled=False), # EDITÁVEL para adicionar manualmente
        "Nome do Produto": st.column_config.TextColumn("Produto", disabled=True), 
        "Forn. Info": st.column_config.TextColumn("Forn. Info", disabled=True), 
        "qtd": st.column_config.NumberColumn("Qtd", min_value=1, step=1, help="Quantidade a ser comprada", format="%d"),
        "valor_unit": st.column_config.NumberColumn("Preço Unitário (R$)", format="R$ %.2f", help="Valor de custo/compra por unidade"),
        "Total": st.column_config.NumberColumn("Total (R$)", format="R$ %.2f", disabled=True), 
        "origem": st.column_config.TextColumn("Origem", disabled=True)
    }
    
    ed = st.data_editor(
        df_exibir, 
        num_rows="dynamic", # Permite ADICIONar LINHAS
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
    
    c_btn1, c_btn2 = st.columns(2)
    
    if c_btn1.button("💾 Salvar OC", type="primary"):
        nid = gerar_numero_oc(ped["empresa"])
        dados = {"id": nid, "empresa": ped["empresa"], "fornecedor": ped["fornecedor"], "data_emissao": dt.date.today().strftime("%Y-%m-%d"), "valor_total": float(tot), "status": "Pendente", "obs": ped["obs"], "itens": st.session_state.pedido_ativo["itens"]}
        if salvar_pedido(dados):
            st.success(f"OC {nid} gerada!"); st.session_state.pedido_ativo["itens"] = []; time.sleep(1); st.rerun()
    if c_btn2.button("🗑️ Limpar"): st.session_state.pedido_ativo["itens"] = []; st.rerun()

# --- TAB 5: GESTÃO (CORRIGIDA PARA IMPRESSÃO E CONTEXTO) ---
with tab5:
    st.header("🗂️ Gestão de Ordens de Compra")
    
    col_print, col_update = st.columns([1, 4])
    
    # BOTÃO DE IMPRIMIR/PDF
    col_print.button("🖨️ Imprimir OC", help="Clique aqui para gerar o PDF da Ordem de Compra. Use o destino 'Salvar como PDF' na tela de impressão.")
    
    if col_update.button("🔄 Atualizar Lista"): st.rerun()
    
    df_ocs = listar_pedidos()
    if not df_ocs.empty:
        # Tabela principal de OCs
        st.dataframe(df_ocs[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Obs"]], use_container_width=True, hide_index=True)
        
        st.markdown("---")
        
        c_a1, c_a2, c_a3 = st.columns([2, 1, 1])
        sel_oc = c_a1.selectbox("Selecione a OC para Gerenciamento:", df_ocs["ID"].unique(), key="sel_oc_gestao")
        
        if sel_oc:
            row = df_ocs[df_ocs["ID"] == sel_oc].iloc[0]
            
            # Atualização de Status
            ns = c_a2.selectbox("Novo Status", ["Pendente", "Aprovado", "Enviado", "Recebido", "Cancelado"], key="new_status_oc")
            if c_a2.button("✔️ Atualizar Status"): atualizar_status(sel_oc, ns); st.success("Status atualizado!"); time.sleep(1); st.rerun()
            
            # Detalhes e Exclusão
            if c_a3.button("🗑️ Excluir", help="Excluir Ordem de Compra.", key="delete_oc_btn"): excluir_pedido_db(sel_oc); st.warning("Excluído"); time.sleep(1); st.rerun()

            with st.expander(f"Detalhes da OC {sel_oc}", expanded=True):
                st.markdown(f"**Fornecedor:** {row['Fornecedor']} | **Empresa:** {row['Empresa']} | **Valor Total:** {format_br_currency(row['Valor'])}")
                st.markdown(f"**Observações:** {row['Obs']}")
                
                itens = row.get("Dados_Completos") # Puxa os dados completos
                if isinstance(itens, list) and len(itens) > 0: 
                    df_itens = pd.DataFrame(itens)
                    
                    # Adiciona Nome do Produto e Fornecedor Info para contexto (COM SEGURANÇA)
                    if st.session_state.catalogo_df is not None:
                        df_cat = st.session_state.catalogo_df.copy()
                        
                        rename_map = {}
                        if 'nome_produto' in df_cat.columns: rename_map['nome_produto'] = 'Nome do Produto'
                        if 'fornecedor' in df_cat.columns: rename_map['fornecedor'] = 'Forn. Info'
                        
                        # CRÍTICO: O catálogo está com 'component_sku', renomeamos para 'sku' apenas para o merge aqui
                        df_cat = df_cat.rename(columns={'component_sku': 'sku'})
                        df_cat = df_cat.rename(columns=rename_map)
                        
                        cols_to_merge = ["sku"]
                        if "Nome do Produto" in df_cat.columns: cols_to_merge.append("Nome do Produto")
                        if "Forn. Info" in df_cat.columns: cols_to_merge.append("Forn. Info")
                        
                        df_itens = df_itens.merge(df_cat[cols_to_merge], on="sku", how="left")
                    
                    df_itens["Total"] = df_itens["qtd"].astype(float) * df_itens["valor_unit"].astype(float)
                    
                    cols_exp = [c for c in ["sku", "Nome do Produto", "Forn. Info", "qtd", "valor_unit", "Total", "origem"] if c in df_itens.columns]
                    
                    st.dataframe(
                        df_itens[cols_exp], 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "valor_unit": st.column_config.NumberColumn("Preço Unitário", format="R$ %.2f"),
                            "Total": st.column_config.NumberColumn("Total", format="R$ %.2f"),
                        }
                    )
                else: 
                    st.write("Sem detalhes dos itens.")

# --- TAB 6: ALOCAÇÃO (ANTIGA TAB 5) ---
with tab6:
    st.header("📦 Alocação de Compra (JCA vs ALIVVIA)")
    
    ra = st.session_state.get("resultado_ALIVVIA")
    rj = st.session_state.get("resultado_JCA")
    
    if ra is None or rj is None:
        st.info("Por favor, calcule ambas as empresas na aba 'Análise' para alocar.")
    else:
        try:
            cols_req = ["SKU", "Vendas_Total_60d", "Estoque_Fisico"]
            # Garante que as colunas existem antes de tentar acessar
            if not all(c in ra.columns for c in cols_req) or not all(c in rj.columns for c in cols_req):
                 st.error("Faltam colunas essenciais nos arquivos carregados para fazer a alocação.")
            else:
                df_A = ra[cols_req].rename(columns={"Vendas_Total_60d": "Vendas_A", "Estoque_Fisico": "Estoque_A"})
                df_J = rj[cols_req].rename(columns={"Vendas_Total_60d": "Vendas_J", "Estoque_Fisico": "Estoque_J"})
                base_aloc = pd.merge(df_A, df_J, on="SKU", how="outer").fillna(0)
                
                sku_aloc = st.selectbox("Selecione o SKU para Alocar:", ["Selecione um SKU"] + base_aloc["SKU"].unique().tolist())
                
                if sku_aloc != "Selecione um SKU":
                    row = base_aloc[base_aloc["SKU"] == sku_aloc].iloc[0]
                    
                    st.markdown("#### Detalhes do SKU")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Vendas ALIVVIA (60d)", format_br_int(row["Vendas_A"]))
                    c2.metric("Vendas JCA (60d)", format_br_int(row["Vendas_J"]))
                    c3.metric("Estoque Físico Total", format_br_int(row["Estoque_A"] + row["Estoque_J"]))
                    
                    st.markdown("---")
                    compra_total = st.number_input(f"Quantidade TOTAL de Compra para {sku_aloc}:", min_value=1, step=1, value=500)
                    
                    venda_total = row["Vendas_A"] + row["Vendas_J"]
                    
                    if venda_total > 0:
                        perc_A = row["Vendas_A"] / venda_total
                        perc_J = row["Vendas_J"] / venda_total
                    else:
                        perc_A = 0.5
                        perc_J = 0.5
                    
                    aloc_A = round(compra_total * perc_A)
                    aloc_J = round(compra_total * perc_J)
                    
                    st.markdown("#### Alocação Sugerida (Baseado em % de Vendas 60d)")
                    
                    col_res1, col_res2 = st.columns(2)
                    col_res1.metric("ALIVVIA (Qtd)", format_br_int(aloc_A))
                    col_res2.metric("JCA (Qtd)", format_br_int(aloc_J))
                    
                    st.markdown("---")
                    st.info("Esta alocação é apenas para fins de compra. As sugestões na aba 'Análise' consideram o estoque atual e a reserva.")
        except Exception as e: 
            st.error(f"Erro ao cruzar dados para alocação: {e}")