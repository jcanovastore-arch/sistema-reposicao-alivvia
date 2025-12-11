import os
import pandas as pd
import streamlit as st
import time
import datetime as dt
import pdfplumber
import re

# Imports internos
from src.config import DEFAULT_SHEET_LINK
from src.utils import style_df_compra, norm_sku, format_br_currency
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets, _carregar_padrao_de_content
from src.logic import Catalogo, mapear_colunas, calcular
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== FUNÇÃO EXTRAÇÃO PDF ML =====================
def extrair_dados_pdf_ml(pdf_bytes):
    """Lê o PDF de envio do ML e extrai SKU e Quantidade declarada."""
    data = []
    try:
        with pdfplumber.open(pd.io.common.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue
                
                # Tenta encontrar linhas que pareçam itens de envio
                # Padrão visual do ML costuma ter o SKU e depois a Qtd
                lines = text.split('\n')
                for line in lines:
                    # Lógica simples: Procura por algo que pareça SKU e um numero no fim
                    # Exemplo de linha ML: "Produto XYZ  SKU123  10 un"
                    parts = line.split()
                    if len(parts) < 2: continue
                    
                    sku_cand = None
                    qtd_cand = 0
                    
                    # Tenta achar a quantidade (geralmente o último ou penúltimo numero)
                    # Varre de tras pra frente procurando numero
                    for p in reversed(parts):
                        if p.replace('.','').isdigit():
                            qtd_cand = int(p.replace('.',''))
                            break
                    
                    # Se achou qtd, tenta achar SKU (partes que tem letra e numero ou só letra maiuscula)
                    # Isso é uma heurística, pode precisar ajustar conforme o layout exato do seu PDF
                    if qtd_cand > 0:
                        # Pega o maior token que parece um SKU na linha
                        possiveis_skus = [x for x in parts if len(x) > 3 and any(c.isalpha() for c in x) and x.isupper()]
                        if possiveis_skus:
                            sku_cand = possiveis_skus[-1] # Geralmente o SKU ta perto da qtd
                            
                            # Limpeza básica do SKU
                            sku_cand = norm_sku(sku_cand)
                            if sku_cand:
                                data.append({"SKU": sku_cand, "Qtd_Envio": qtd_cand})
                                
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
    
    # Filtra apenas o que precisa comprar
    if "Faltam_Comprar" not in df_source.columns:
        st.error("Erro: Coluna 'Faltam_Comprar' não encontrada.")
        return

    df_buy = df_source[df_source["Faltam_Comprar"] > 0].copy()
    if df_buy.empty:
        st.toast("Nada faltante para comprar!", icon="✅")
        return

    curr = st.session_state.pedido_ativo["itens"]
    curr_skus = [i["sku"] for i in curr]
    c = 0
    for _, r in df_buy.iterrows():
        if r["SKU"] not in curr_skus:
            # Busca preço se disponível
            preco = 0.0
            if "Preco" in r: preco = float(r["Preco"])
            
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
    if st.button("🔄 Baixar do Google Sheets"):
        try:
            c, origem = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success(f"Carregado via {origem}!")
        except Exception as e: 
            st.error(f"Erro: {e}"); st.warning("Use o upload manual abaixo.")
    up_manual = st.file_uploader("Ou 'Padrao_produtos.xlsx' manual:", type=["xlsx"])
    if up_manual:
        try:
            c = _carregar_padrao_de_content(up_manual.getvalue())
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("✅ Carregado!")
        except Exception as e: st.error(f"Erro: {e}")

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
        f1, f2 = st.columns(2)
        sku_f = f1.text_input("🔎 SKU", key="f_sku", on_change=reset_selection).upper()
        
        for emp in ["ALIVVIA", "JCA"]:
            if st.session_state.get(f"resultado_{emp}") is not None:
                st.markdown(f"### 📊 {emp}")
                df = st.session_state[f"resultado_{emp}"].copy()
                if sku_f: df = df[df["SKU"].str.contains(sku_f, na=False)]
                
                k_sku = f"c_skus_{emp}"
                st.session_state[k_sku] = df["SKU"].tolist()
                sel = st.session_state[f"sel_{emp[0]}"]
                df.insert(0, "Selecionar", df["SKU"].map(lambda x: sel.get(x, False)))
                
                cols = [c for c in ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida"] if c in df.columns]
                st.data_editor(style_df_compra(df[cols]), key=f"ed_{emp}", use_container_width=True, hide_index=True, column_config={"Selecionar": st.column_config.CheckboxColumn(default=False)}, on_change=update_sel, args=(f"ed_{emp}", k_sku, sel))
                if st.button(f"🛒 Add ao Pedido ({emp})", key=f"bt_{emp}"): add_to_cart(emp)

# --- TAB 3: CRUZAMENTO PDF FULL (NOVA LÓGICA) ---
with tab3:
    st.header("🚛 Cruzar PDF de Envio vs Estoque Físico")
    st.info("Faça upload do PDF gerado pelo Mercado Livre. O sistema vai verificar se você tem estoque para enviar.")
    
    emp_pdf = st.radio("Empresa do Envio:", ["ALIVVIA", "JCA"], horizontal=True)
    pdf_file = st.file_uploader("Arrastar PDF do Envio Full", type=["pdf"])
    
    df_res = st.session_state.get(f"resultado_{emp_pdf}")
    
    if df_res is None:
        st.warning(f"⚠️ Primeiro vá na aba 'Análise & Compra' e clique em 'Calc {emp_pdf}' para carregar o Estoque Físico atual.")
    elif pdf_file:
        st.write("Lendo PDF...")
        df_pdf = extrair_dados_pdf_ml(pdf_file.getvalue())
        
        if df_pdf.empty:
            st.error("Não consegui ler itens no PDF. Verifique se é um arquivo de envio válido.")
        else:
            st.success(f"Encontrados {len(df_pdf)} itens no PDF.")
            
            # Cruzamento
            # df_res tem "SKU" e "Estoque_Fisico" (e Preco, Fornecedor)
            df_merged = df_pdf.merge(df_res[["SKU", "Estoque_Fisico", "fornecedor", "Preco"]], on="SKU", how="left")
            
            # Se não achou no estoque fisico, assume 0
            df_merged["Estoque_Fisico"] = df_merged["Estoque_Fisico"].fillna(0).astype(int)
            df_merged["Preco"] = df_merged["Preco"].fillna(0)
            
            # Lógica: O que falta?
            # Se Qtd_Envio > Fisico, falta comprar a diferença
            df_merged["Faltam_Comprar"] = (df_merged["Qtd_Envio"] - df_merged["Estoque_Fisico"]).clip(lower=0)
            
            # Exibição
            st.write("### Resultado da Análise do PDF")
            
            # Estilização
            def highlight_falta(s):
                return ['background-color: #ffcccc' if v > 0 else '' for v in s]

            st.dataframe(
                df_merged[["SKU", "Qtd_Envio", "Estoque_Fisico", "Faltam_Comprar", "fornecedor"]].style.apply(highlight_falta, subset=["Faltam_Comprar"]),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Qtd_Envio": st.column_config.NumberColumn("Qtd no PDF"),
                    "Faltam_Comprar": st.column_config.NumberColumn("🛑 Faltam Comprar")
                }
            )
            
            # Botão Mágico
            total_falta = df_merged["Faltam_Comprar"].sum()
            if total_falta > 0:
                if st.button(f"🛒 Adicionar {int(total_falta)} itens faltantes ao Pedido de Compra", type="primary"):
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
        df_i["Total"] = df_i["qtd"] * df_i["valor_unit"]
        ed = st.data_editor(df_i, num_rows="dynamic", use_container_width=True, key="ed_oc")
        tot = ed["Total"].sum()
        st.metric("Total Pedido", format_br_currency(tot))
        if st.button("💾 Salvar OC", type="primary"):
            nid = gerar_numero_oc(ped["empresa"])
            dados = {"id": nid, "empresa": ped["empresa"], "fornecedor": ped["fornecedor"], "data_emissao": dt.date.today().strftime("%Y-%m-%d"), "valor_total": float(tot), "status": "Pendente", "obs": ped["obs"], "itens": ed.to_dict("records")}
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
            df_A = ra[["SKU", "Vendas_Total_60d", "Estoque_Fisico"]].rename(columns={"Vendas_Total_60d": "Vendas_A", "Estoque_Fisico": "Estoque_A"})
            df_J = rj[["SKU", "Vendas_Total_60d", "Estoque_Fisico"]].rename(columns={"Vendas_Total_60d": "Vendas_J", "Estoque_Fisico": "Estoque_J"})
            base = pd.merge(df_A, df_J, on="SKU", how="outer").fillna(0)
            sku = st.selectbox("SKU:", ["Selecione"] + base["SKU"].unique().tolist())
            if sku != "Selecione":
                r = base[base["SKU"] == sku].iloc[0]
                c1,c2,c3 = st.columns(3)
                c1.metric("Vendas A", int(r["Vendas_A"])); c2.metric("Vendas J", int(r["Vendas_J"])); c3.metric("Físico Total", int(r["Estoque_A"]+r["Estoque_J"]))
                compra = st.number_input("Qtd Compra:", min_value=1, value=500)
                tot_v = r["Vendas_A"] + r["Vendas_J"]
                perc = (r["Vendas_A"]/tot_v) if tot_v > 0 else 0.5
                st.info(f"Sugestão: {int(compra*perc)} Alivvia | {int(compra*(1-perc))} JCA")
        except: st.error("Erro ao cruzar dados para alocação.")