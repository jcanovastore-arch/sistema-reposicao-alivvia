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
            if ft not in st.session_state[emp]: st.session_state[emp][ft] = {"name": None, "bytes": None}
            # Tenta carregar cache local
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
    """Remove o arquivo .bin e .txt do cache local"""
    file_path = get_local_file_path(empresa, tipo)
    name_path = get_local_name_path(empresa, tipo)
    
    deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        deleted = True
    if os.path.exists(name_path):
        os.remove(name_path)
        deleted = True
        
    st.session_state[empresa][tipo]["name"] = None
    st.session_state[empresa][tipo]["bytes"] = None
    
    if deleted:
        st.toast(f"Cache de {empresa} {tipo} limpo!", icon="🧹")
        time.sleep(1)
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
            # CRÍTICO: Garantir a compatibilidade do nome da coluna sku (component_sku)
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
            # CRÍTICO: Garantir a compatibilidade do nome da coluna sku (component_sku)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("✅ Arquivo carregado manualmente!")
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

st.title("Reposição Logística — Alivvia")
if st.session_state.catalogo_df is None: st.warning("⚠️ Carregue o Padrão de Produtos no menu lateral.")

# 🛑 NOVO LAYOUT DE 6 ABAS (CRÍTICO)
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📂 Uploads", "🔍 Análise & Compra", "🚛 Cruzar PDF Full", "📝 Editor OC", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS ---
with tab1:
    c1, c2 = st.columns(2)
    def up_block(emp, col):
        with col:
            st.subheader(emp)
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                curr_state = st.session_state[emp][ft]
                
                f = st.file_uploader(ft, key=f"u_{emp}_{ft}")
                
                if f:
                    with open(get_local_file_path(emp, ft), 'wb') as fb: fb.write(f.read())
                    with open(get_local_name_path(emp, ft), 'w') as fn: fn.write(f.name)
                    st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue()}
                    st.success("Salvo!")
                
                if curr_state["name"]:
                    col_name, col_btn = st.columns([3, 1])
                    col_name.caption(f"✅ {curr_state['name']}")
                    if col_btn.button("🧹 Limpar", key=f"clean_{emp}_{ft}"):
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
                # Necessário importar as funções que o script original não tinha
                from src.logic import mapear_colunas, load_any_table_from_bytes, Catalogo, calcular
                
                full = mapear_colunas(load_any_table_from_bytes(s["FULL"]["name"], s["FULL"]["bytes"]), "FULL")
                vend = mapear_colunas(load_any_table_from_bytes(s["VENDAS"]["name"], s["VENDAS"]["bytes"]), "VENDAS")
                fis = pd.DataFrame()
                if s["ESTOQUE"]["bytes"]:
                    fis = mapear_colunas(load_any_table_from_bytes(s["ESTOQUE"]["name"], s["ESTOQUE"]["bytes"]), "FISICO")
                # CRÍTICO: Garantir que a coluna 'sku' está no catalogo simples para passar para a lógica
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
                        "Estoque_Fisico": st.column_config.NumberColumn("Físico (Bruto)", help="Estoque lido diretamente do arquivo."),
                        "Preco": st.column_config.NumberColumn("Preço Unitário", format="R$ %.2f"),
                        "Valor_Compra_R$": st.column_config.NumberColumn("Valor Compra", format="R$ %.2f")
                    },
                    on_change=update_sel, 
                    args=(f"ed_{emp}", k_sku, sel)
                )
                
                if st.button(f"🛒 Enviar Selecionados ({emp}) para Editor", key=f"bt_{emp}"): 
                    add_to_cart(emp)

# --- TAB 3: CRUZAR PDF FULL (RESTAURADO) ---
with tab3:
    st.header("🚛 Cruzar PDF Full")
    st.info("Carregue o PDF de Instruções de Preparação do Mercado Livre Full.")

    c_pdf, c_btn = st.columns([3, 1])
    pdf_file = c_pdf.file_uploader("Upload PDF:", type=["pdf"], key="pdf_full_upload")
    
    if pdf_file:
        df_pdf = extrair_dados_pdf_ml(pdf_file.getvalue())
        
        if not df_pdf.empty:
            st.success(f"{len(df_pdf)} SKUs extraídos com sucesso do PDF.")
            
            # 1. Merge com o Catálogo para obter preço e nome
            if st.session_state.catalogo_df is not None:
                # Garante que as colunas do catálogo usadas para merge estão formatadas
                df_cat = st.session_state.catalogo_df.copy()
                df_cat["SKU"] = df_cat["sku"].apply(norm_sku)
                
                # Mapeamento seguro de colunas do catálogo (se existirem)
                cols_to_use = ["SKU"]
                if "nome_produto" in df_cat.columns: cols_to_use.append("nome_produto")
                if "preco" in df_cat.columns: cols_to_use.append("preco")
                
                df_merge = df_pdf.merge(df_cat[cols_to_use], on="SKU", how="left")
                
                # Renomeia e calcula valor total
                df_merge = df_merge.rename(columns={"nome_produto": "Nome do Produto", "preco": "Preco"})
                df_merge["Preco"] = pd.to_numeric(df_merge["Preco"], errors='coerce').fillna(0)
                df_merge["Valor_Total"] = (df_merge["Qtd_Envio"] * df_merge["Preco"]).round(2)
                df_pdf = df_merge # Usa o DF mesclado
            else:
                 df_pdf["Valor_Total"] = 0.0 # Define um valor padrão se não tiver catálogo
            
            cols_display_pdf = [c for c in ["SKU", "Nome do Produto", "Qtd_Envio", "Preco", "Valor_Total"] if c in df_pdf.columns]
            
            st.data_editor(
                df_pdf[cols_display_pdf],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Qtd_Envio": st.column_config.NumberColumn("Qtd PDF", format="%d", disabled=True),
                    "Preco": st.column_config.NumberColumn("Preço (Catálogo)", format="R$ %.2f", disabled=True),
                    "Valor_Total": st.column_config.NumberColumn("Total (R$)", format="R$ %.2f", disabled=True),
                }
            )

            # 2. Botão para adicionar ao carrinho 
            if c_btn.button("🛒 Enviar para Editor OC", type="primary"):
                curr = st.session_state.pedido_ativo["itens"]
                # Usa um dicionário para permitir somar quantidades se o SKU já estiver no carrinho
                curr_skus_dict = {i["sku"]: i for i in curr} 
                c = 0

                for _, r in df_pdf.iterrows():
                    sku = r["SKU"]
                    qtd = r["Qtd_Envio"]
                    preco = r["Preco"] if "Preco" in r and r["Preco"] is not None else 0.0 # Segurança
                    origem = "PDF_FULL"

                    if qtd > 0:
                        if sku in curr_skus_dict:
                             curr_skus_dict[sku]["qtd"] += qtd
                        else:
                            curr_skus_dict[sku] = {
                                "sku": sku, 
                                "qtd": int(qtd), # Garante que é inteiro
                                "valor_unit": float(preco), # Garante que é float
                                "origem": origem
                            }
                        c += 1
                
                st.session_state.pedido_ativo["itens"] = list(curr_skus_dict.values())
                st.toast(f"{c} itens do PDF adicionados ou somados ao pedido!", icon="🛒")

        else:
            st.warning("Não foi possível extrair SKUs do PDF.")
    else:
        st.info("Aguardando upload do PDF de Full.")

# --- TAB 4: EDITOR OC (ANTIGA TAB 3 - AGORA CORRIGIDA) ---
with tab4:
    st.header("📝 Editor de Ordem de Compra")
    st.info("⚠️ Para adicionar um item manualmente, digite o SKU, Qtd e Preço Unitário na última linha da tabela.")
    ped = st.session_state.pedido_ativo
    c1, c2, c3 = st.columns(3)
    ped["fornecedor"] = c1.text_input("Fornecedor", ped["fornecedor"])
    ped["empresa"] = c2.selectbox("Empresa OC", ["ALIVVIA", "JCA"])
    ped["obs"] = c3.text_input("Obs", ped["obs"])
    
    # 🛑 A CORREÇÃO CRÍTICA É CRIAR UM DATAFRAME VAZIO SE O CARRINHO ESTIVER VAZIO
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
        num_rows="dynamic", # Permite ADICIONAR LINHAS
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

# --- TAB 5: GESTÃO (ANTIGA TAB 4 - CORRIGIDA PARA IMPRESSÃO E CONTEXTO) ---
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