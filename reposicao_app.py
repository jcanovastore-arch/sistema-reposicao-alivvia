import os
import pandas as pd
import streamlit as st
import time
import datetime as dt
import pdfplumber 
import re 
import io 
import numpy as np 
from typing import Optional, Tuple

# Imports internos
from src.config import DEFAULT_SHEET_LINK, STORAGE_DIR
from src.utils import style_df_compra, norm_sku, format_br_currency, format_br_int 
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets, _carregar_padrao_de_content
from src.logic import Catalogo, mapear_colunas, calcular, explodir_por_kits, construir_kits_efetivo
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== FUNÇÕES DE CACHE E UTILS =====================
def get_local_timestamp_path(empresa: str, tipo: str) -> str:
    """Retorna o caminho local para o arquivo de timestamp."""
    return os.path.join(STORAGE_DIR, f"{empresa}_{tipo}_time.txt")

def get_br_datetime() -> dt.datetime:
    """Retorna o datetime atual ajustado para o fuso horário de Brasília (UTC-3)."""
    now_naive = dt.datetime.now()
    now_br = now_naive - dt.timedelta(hours=3)
    return now_br

# 🛑 FUNÇÃO: MAPEAMENTO POR APROXIMAÇÃO (FUZZY SIMPLIFICADO)
def find_closest_sku(broken_sku: str, catalog_skus: set) -> Optional[str]:
    """
    Tenta encontrar a melhor correspondência do SKU quebrado no catálogo.
    """
    # Remove espaços e quebras de linha para comparação limpa
    broken_sku = norm_sku(broken_sku).replace(' ', '').replace('\n', '')
    if not broken_sku: return None
    
    # Busca o SKU completo mais longo que COMEÇA com o SKU quebrado.
    sorted_catalog = sorted([s for s in catalog_skus if s.startswith(broken_sku)], key=len, reverse=True)
    
    if sorted_catalog:
        return sorted_catalog[0]
        
    return None

def map_broken_skus(df_pdf: pd.DataFrame, catalogo_df: pd.DataFrame) -> pd.DataFrame:
    """Aplica o mapeamento por aproximação aos SKUs lidos do PDF/Excel."""
    if catalogo_df is None or catalogo_df.empty:
        return df_pdf
        
    catalog_skus = set(catalogo_df["component_sku"].apply(norm_sku).unique())
    
    df_pdf["SKU_Mapeado"] = df_pdf["SKU"].apply(lambda x: find_closest_sku(x, catalog_skus))
    
    # Filtra apenas o que conseguiu mapear
    df_mapped = df_pdf.dropna(subset=["SKU_Mapeado"]).copy()
    df_mapped["SKU"] = df_mapped["SKU_Mapeado"]
    
    return df_mapped.groupby("SKU", as_index=False)["Qtd_Envio"].sum() 

# ===================== FUNÇÕES DE LEITURA (PDF E EXCEL/CSV) =====================

def extrair_dados_excel_ml(file_obj) -> pd.DataFrame:
    """Lê o arquivo Excel/CSV convertido do PDF com Regex ESTRITA."""
    try:
        # Tenta ler como CSV ou Excel
        try:
            df = pd.read_csv(file_obj, sep=None, engine='python')
        except:
            file_obj.seek(0)
            df = pd.read_excel(file_obj)
            
        # Procura a linha de cabeçalho
        header_row = None
        for i in range(min(20, len(df))):
            row_vals = df.iloc[i].astype(str).str.upper().tolist()
            if any("UNIDADES" in v for v in row_vals) and any("PRODUTO" in v for v in row_vals):
                header_row = i
                break
        
        if header_row is not None:
            df.columns = df.iloc[header_row]
            df = df.iloc[header_row+1:].copy()
        
        # Identifica colunas
        col_prod = next((c for c in df.columns if "PRODUTO" in str(c).upper()), None)
        col_qtd = next((c for c in df.columns if "UNIDADES" in str(c).upper()), None)
        
        if not col_prod or not col_qtd:
            st.error("Não encontrei as colunas 'PRODUTO' e 'UNIDADES' no Excel.")
            return pd.DataFrame()
            
        data = []
        # 🛑 REGEX V38: [\w\-\/]+
        # Isso significa: Pegue letras, números, hífens e barras.
        # PARE assim que encontrar um espaço ou quebra de linha.
        regex_sku = re.compile(r'SKU:?\s*([\w\-\/]+)', re.IGNORECASE)
        
        for _, row in df.iterrows():
            prod_text = str(row[col_prod])
            qtd_val = row[col_qtd]
            
            # Extrai SKU do texto da coluna PRODUTO
            match = regex_sku.search(prod_text)
            if match:
                sku = match.group(1).strip()
                try:
                    # Limpa a quantidade
                    qtd_str = str(qtd_val).replace(',', '.')
                    if not qtd_str.strip(): continue
                    qtd = int(float(qtd_str))
                    if qtd > 0:
                        data.append({"SKU": sku, "Qtd_Envio": qtd})
                except:
                    pass
                    
        return pd.DataFrame(data).groupby("SKU", as_index=False)["Qtd_Envio"].sum()
        
    except Exception as e:
        st.error(f"Erro ao ler Excel/CSV: {e}")
        return pd.DataFrame()

def extrair_dados_pdf_ml(pdf_bytes):
    """Lê o PDF usando a estratégia de BLOCOS (V36)."""
    data = []
    regex_sku_finder = re.compile(r'SKU:?\s*([\w\-\/\s]+)', re.IGNORECASE)
    regex_qtd_finder = re.compile(r'\b(\d{1,5})\b') 

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue

                text = text.replace("404", "XXX") # Vacina 404

                # Estratégia de Blocos
                text_marked = re.sub(r'(Código\s*ML[:\s])', r'||BLOCK||\1', text, flags=re.IGNORECASE)
                blocks = text_marked.split('||BLOCK||')

                for block in blocks:
                    if not block.strip(): continue

                    match_sku = regex_sku_finder.search(block)
                    if match_sku:
                        sku_raw = match_sku.group(1).strip()
                        numbers = regex_qtd_finder.findall(block)
                        
                        found_qty = None
                        for num_str in numbers:
                            try:
                                val = int(num_str)
                                num_in_sku = re.search(r'\d+', sku_raw)
                                if num_in_sku and num_in_sku.group(0) == num_str: continue 
                                if 0 < val < 10000:
                                    found_qty = val
                                    break 
                            except: continue
                        
                        if found_qty:
                            data.append({"SKU": sku_raw, "Qtd_Envio": found_qty})

            if not data: return pd.DataFrame()
            return pd.DataFrame(data).drop_duplicates().groupby("SKU", as_index=False)["Qtd_Envio"].sum()

    except Exception as e:
        st.error(f"Erro CRÍTICO ao ler PDF: {e}")
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
            if ft not in st.session_state[emp] or "timestamp" not in st.session_state[emp][ft]: 
                st.session_state[emp][ft] = {"name": None, "bytes": None, "timestamp": None}
            if not st.session_state[emp][ft]["name"]:
                try:
                    p = get_local_file_path(emp, ft)
                    n = get_local_name_path(emp, ft)
                    t = get_local_timestamp_path(emp, ft)
                    if os.path.exists(p):
                        with open(p, 'rb') as f: st.session_state[emp][ft]["bytes"] = f.read()
                        with open(n, 'r') as f: st.session_state[emp][ft]["name"] = f.read().strip()
                        if os.path.exists(t):
                             with open(t, 'r') as f: st.session_state[emp][ft]["timestamp"] = f.read().strip()
                        else:
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
    if df_source is None or df_source.empty: return
    if "Faltam_Comprar" not in df_source.columns: return
    df_buy = df_source[df_source["Faltam_Comprar"] > 0].copy()
    if df_buy.empty: return st.toast("Nada faltante para comprar!", icon="✅")
    curr = st.session_state.pedido_ativo["itens"]
    curr_skus = [i["sku"] for i in curr]
    c = 0
    for _, r in df_buy.iterrows():
        if r["SKU"] not in curr_skus:
            preco = float(r.get("Preco", 0.0))
            curr.append({"sku": r["SKU"], "qtd": int(r["Faltam_Comprar"]), "valor_unit": preco, "origem": f"FULL_{emp}"})
            c += 1
    st.session_state.pedido_ativo["itens"] = curr
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
        qtd = int(r.get("Compra_Sugerida", 0))
        if r["SKU"] not in curr_skus and qtd > 0:
            curr.append({"sku": r["SKU"], "qtd": qtd, "valor_unit": float(r.get("Preco", 0)), "origem": emp})
            c += 1
    st.session_state.pedido_ativo["itens"] = curr
    if not st.session_state.pedido_ativo["fornecedor"] and not novos.empty:
        st.session_state.pedido_ativo["fornecedor"] = novos.iloc[0]["fornecedor"]
    st.toast(f"{c} itens adicionados!")
    
def clear_file_cache(empresa, tipo):
    file_path = get_local_file_path(empresa, tipo)
    name_path = get_local_name_path(empresa, tipo)
    time_path = get_local_timestamp_path(empresa, tipo) 
    deleted = False
    if os.path.exists(file_path): os.remove(file_path); deleted = True
    if os.path.exists(name_path): os.remove(name_path); deleted = True
    if os.path.exists(time_path): os.remove(time_path)
    st.session_state[empresa][tipo] = {"name": None, "bytes": None, "timestamp": None}
    st.session_state[f"resultado_{empresa}"] = None
    if deleted:
        st.toast(f"Cache de {empresa} {tipo} limpo! Recarregando...", icon="🧹")
        time.sleep(1); st.rerun()

def reset_master_data():
    st.session_state.catalogo_df = None; st.session_state.kits_df = None
    st.toast("Dados Mestre limpos! Recarregando...", icon="🧹"); st.rerun() 

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
            st.session_state.catalogo_df = c.catalogo_simples
            st.session_state.kits_df = c.kits_reais
            st.success(f"Carregado via {origem}!")
        except Exception as e: st.error(f"Erro: {e}"); st.warning("Use o upload manual.")
    up_manual = st.file_uploader("Ou 'Padrao_produtos.xlsx' manual:", type=["xlsx"])
    if up_manual:
        try:
            from src.data import _carregar_padrao_de_content 
            c = _carregar_padrao_de_content(up_manual.getvalue())
            st.session_state.catalogo_df = c.catalogo_simples
            st.session_state.kits_df = c.kits_reais
            st.success("✅ Arquivo carregado!")
        except Exception as e: st.error(f"Erro: {e}")
    st.divider()
    st.button("🧹 Limpar Dados Mestre", type="secondary", on_click=reset_master_data)

st.title("Reposição Logística — Alivvia")
if st.session_state.catalogo_df is None: 
    st.warning("⚠️ Carregue o Padrão de Produtos no menu lateral.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📂 Uploads", "🔍 Análise & Compra", "🚛 Cruzar PDF Full", "📝 Editor OC", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS ---
with tab1:
    st.subheader("⚠️ Arquivos Operacionais")
    c1, c2 = st.columns(2)
    def up_block(emp, col):
        with col:
            st.markdown(f"### {emp}")
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                curr_state = st.session_state[emp][ft]
                file_types = ["xlsx", "csv"]
                if ft == "FULL": file_types.append("pdf")
                f = st.file_uploader(f"Upload {ft}", type=file_types, key=f"u_{emp}_{ft}")
                if f and (f.name != curr_state.get("name") or not curr_state.get("name")):
                        now_br = get_br_datetime()
                        timestamp_str = now_br.strftime("%d/%m/%Y %H:%M:%S")
                        with open(get_local_file_path(emp, ft), 'wb') as fb: fb.write(f.getvalue())
                        with open(get_local_name_path(emp, ft), 'w') as fn: fn.write(f.name)
                        with open(get_local_timestamp_path(emp, ft), 'w') as ft_w: ft_w.write(timestamp_str)
                        st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue(), "timestamp": timestamp_str}
                        st.toast(f"✅ {f.name} Salvo!", icon="✅"); time.sleep(1); st.rerun() 
                if curr_state["name"]:
                    st.caption(f"**Atual:** {curr_state['name']} ({curr_state['timestamp']})")
                    if st.button("🧹 Limpar", key=f"clean_{emp}_{ft}"): clear_file_cache(emp, ft)
    up_block("ALIVVIA", c1); up_block("JCA", c2)

# --- TAB 2: ANÁLISE ---
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
                cat = Catalogo(st.session_state.catalogo_df, st.session_state.kits_df)
                res, _ = calcular(full, fis, vend, cat, h_p, g_p, lt_p)
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} OK!")
            except Exception as e: st.error(f"Erro: {e}")
        
        if c1.button("Calc ALIVVIA", use_container_width=True): run_calc("ALIVVIA")
        if c2.button("Calc JCA", use_container_width=True): run_calc("JCA")
        st.divider()
        f1, f2 = st.columns(2)
        sku_f = f1.text_input("🔎 Filtro SKU", key="f_sku", on_change=reset_selection).upper()
        forns = set()
        if st.session_state.resultado_ALIVVIA is not None: forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].dropna().unique())
        if st.session_state.resultado_JCA is not None: forns.update(st.session_state.resultado_JCA["fornecedor"].dropna().unique())
        forn_f = f2.selectbox("🏭 Filtro Fornecedor", ["TODOS"] + sorted(list(forns)), key="f_forn", on_change=reset_selection)
        
        for emp in ["ALIVVIA", "JCA"]:
            if st.session_state.get(f"resultado_{emp}") is not None:
                st.markdown(f"### 📊 {emp}")
                df = st.session_state[f"resultado_{emp}"].copy()
                if sku_f: df = df[df["SKU"].str.contains(sku_f, na=False)]
                if forn_f != "TODOS": df = df[df["fornecedor"] == forn_f]
                if not df.empty:
                    cols = ["Estoque_Fisico", "Preco", "Estoque_Full"]
                    for c in cols: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Físico (Un)", format_br_int(df['Estoque_Fisico'].sum()))
                    m2.metric("Físico (R$)", format_br_currency((df['Estoque_Fisico']*df['Preco']).sum()))
                    m3.metric("Full (Un)", format_br_int(df['Estoque_Full'].sum()))
                    m4.metric("Full (R$)", format_br_currency((df['Estoque_Full']*df['Preco']).sum()))
                
                k_sku = f"current_skus_{emp}"
                st.session_state[k_sku] = df["SKU"].tolist()
                sel = st.session_state[f"sel_{emp[0]}"]
                df.insert(0, "Selecionar", df["SKU"].map(lambda x: sel.get(x, False)))
                st.data_editor(
                    style_df_compra(df[["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"]]), 
                    key=f"ed_{emp}", use_container_width=True, hide_index=True,
                    column_config={"Selecionar": st.column_config.CheckboxColumn(default=False), "Estoque_Fisico": st.column_config.NumberColumn(format="%d"), "Preco": st.column_config.NumberColumn(format="R$ %.2f"), "Valor_Compra_R$": st.column_config.NumberColumn(format="R$ %.2f")},
                    on_change=update_sel, args=(f"ed_{emp}", k_sku, sel)
                )
                if st.button(f"🛒 Enviar Selecionados ({emp})", key=f"bt_{emp}"): add_to_cart(emp)

# --- TAB 3: CRUZAR PDF/EXCEL FULL (HÍBRIDO V38) ---
with tab3:
    st.header("🚛 Cruzar PDF ou Excel Full")
    st.info("💡 DICA: Para precisão total, use o arquivo convertido em Excel ou CSV!")
    
    emp_pdf = st.radio("Empresa do Envio:", ["ALIVVIA", "JCA"], horizontal=True, key="emp_pdf_full")
    file_full = st.file_uploader("Upload PDF ou Excel/CSV de Instruções", type=["pdf", "xlsx", "csv"], key="full_upload_tab3")
    
    df_res = st.session_state.get(f"resultado_{emp_pdf}")
    
    if df_res is None:
        st.warning(f"⚠️ Calcule a aba 'Análise & Compra' ({emp_pdf}) primeiro.")
    elif file_full:
        if st.session_state.catalogo_df is None:
             st.error("🛑 Padrão de Produtos não carregado.")
        else:
            st.write("Processando arquivo...")
            
            # DECISOR DE FORMATO
            if file_full.name.lower().endswith('.pdf'):
                df_bruto = extrair_dados_pdf_ml(file_full.getvalue())
            else:
                df_bruto = extrair_dados_excel_ml(file_full)
            
            if df_bruto.empty:
                st.error("Não consegui ler itens.")
            else:
                # 1. Fuzzy Match
                df_mapeado = map_broken_skus(df_bruto, st.session_state.catalogo_df)
                
                if df_mapeado.empty:
                    st.error("Nenhum SKU reconhecido.")
                    st.dataframe(df_bruto)
                else:
                    cat_obj = Catalogo(st.session_state.catalogo_df, st.session_state.kits_df)
                    kits_validos = construir_kits_efetivo(cat_obj)
                    
                    # 2. Explosão de Kits
                    df_exploded = explodir_por_kits(df_mapeado, kits_validos, "SKU", "Qtd_Envio")
                    df_exploded = df_exploded.rename(columns={"Quantidade": "Qtd_Necessaria_Envio"})
                    
                    # 3. Cruzamento
                    cols_to_merge = ["SKU", "Estoque_Fisico", "fornecedor", "Preco"]
                    df_merged = df_exploded.merge(df_res[cols_to_merge], on="SKU", how="left")
                    
                    df_merged["Estoque_Fisico"] = df_merged["Estoque_Fisico"].fillna(0).astype(int)
                    df_merged["Preco"] = pd.to_numeric(df_merged["Preco"], errors='coerce').fillna(0.0)
                    df_merged["Faltam_Comprar"] = (df_merged["Qtd_Necessaria_Envio"] - df_merged["Estoque_Fisico"]).clip(lower=0).astype(int)
                    
                    df_merged["Custo_Total_Envio"] = (df_merged["Qtd_Necessaria_Envio"] * df_merged["Preco"]).round(2)
                    df_merged["Valor_Compra_Faltante"] = (df_merged["Faltam_Comprar"] * df_merged["Preco"]).round(2)
                    
                    st.write(f"### Resultado ({len(df_bruto)} Itens Lidos)")
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Custo Total Envio", format_br_currency(df_merged["Custo_Total_Envio"].sum()))
                    c2.metric("Compra Faltante", format_br_currency(df_merged["Valor_Compra_Faltante"].sum()))
                    c3.metric("Peças Faltantes", format_br_int(df_merged['Faltam_Comprar'].sum()))
                    
                    def highlight_falta(s): return ['background-color: #8B0000; color: white' if v > 0 else '' for v in s]
                    
                    cols_view = ["SKU", "Qtd_Necessaria_Envio", "Estoque_Fisico", "Faltam_Comprar", "Preco", "Valor_Compra_Faltante", "fornecedor"]
                    st.dataframe(
                        df_merged[cols_view].style.format({
                            "Qtd_Necessaria_Envio": "{:.0f}", "Estoque_Fisico": "{:.0f}", "Faltam_Comprar": "{:.0f}", 
                            "Preco": "R$ {:.2f}", "Valor_Compra_Faltante": "R$ {:.2f}"
                        }).apply(highlight_falta, subset=["Faltam_Comprar"]),
                        use_container_width=True, hide_index=True
                    )
                    
                    tf = df_merged["Faltam_Comprar"].sum()
                    if tf > 0:
                        if st.button(f"🛒 Add {tf} peças ao Pedido", type="primary"): add_to_cart_full(df_merged, emp_pdf)
                    else:
                        st.balloons(); st.success("Estoque suficiente!")

# --- TAB 4: EDITOR OC ---
with tab4:
    st.header("📝 Editor OC")
    ped = st.session_state.pedido_ativo
    c1, c2, c3 = st.columns(3)
    ped["fornecedor"] = c1.text_input("Fornecedor", ped["fornecedor"])
    ped["empresa"] = c2.selectbox("Empresa OC", ["ALIVVIA", "JCA"])
    ped["obs"] = c3.text_input("Obs", ped["obs"])
    
    df_i = pd.DataFrame(ped["itens"]) if ped["itens"] else pd.DataFrame(columns=["sku", "qtd", "valor_unit", "origem"])
    df_i = df_i.astype({"sku": str, "qtd": int, "valor_unit": float, "origem": str})
    
    if st.session_state.catalogo_df is not None:
         df_cat = st.session_state.catalogo_df.copy().rename(columns={'component_sku': 'sku', 'nome_produto': 'Nome do Produto', 'fornecedor': 'Forn. Info'})
         cols = [c for c in ["sku", "Nome do Produto", "Forn. Info"] if c in df_cat.columns]
         df_i = df_i.merge(df_cat[cols], on="sku", how="left")
    
    df_i["Total"] = (df_i["qtd"] * df_i["valor_unit"]).round(2)
    cols_dsp = [c for c in ["sku", "Nome do Produto", "Forn. Info", "qtd", "valor_unit", "Total", "origem"] if c in df_i.columns]
    
    ed = st.data_editor(
        df_i[cols_dsp], num_rows="dynamic", use_container_width=True, key="ed_oc", hide_index=True,
        column_config={
            "sku": st.column_config.TextColumn("SKU"),
            "qtd": st.column_config.NumberColumn("Qtd", format="%d"),
            "valor_unit": st.column_config.NumberColumn("Unit (R$)", format="R$ %.2f"),
            "Total": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
            "Nome do Produto": st.column_config.TextColumn(disabled=True),
            "origem": st.column_config.TextColumn(disabled=True)
        }
    )
    st.session_state.pedido_ativo["itens"] = ed[["sku", "qtd", "valor_unit", "origem"]].to_dict("records")
    tot = (ed["qtd"] * ed["valor_unit"]).sum()
    st.metric("Total Pedido", format_br_currency(tot))
    
    cb1, cb2 = st.columns(2)
    if cb1.button("💾 Salvar OC", type="primary"):
        nid = gerar_numero_oc(ped["empresa"])
        if salvar_pedido({"id": nid, "empresa": ped["empresa"], "fornecedor": ped["fornecedor"], "data_emissao": dt.date.today().strftime("%Y-%m-%d"), "valor_total": float(tot), "status": "Pendente", "obs": ped["obs"], "itens": st.session_state.pedido_ativo["itens"]}):
            st.success(f"OC {nid} gerada!"); st.session_state.pedido_ativo["itens"] = []; time.sleep(1); st.rerun()
    if cb2.button("🗑️ Limpar"): st.session_state.pedido_ativo["itens"] = []; st.rerun()

# --- TAB 5: GESTÃO ---
with tab5:
    st.header("🗂️ Gestão OC")
    c_p, c_u = st.columns([1,4])
    c_p.button("🖨️ Imprimir")
    if c_u.button("🔄 Atualizar"): st.rerun()
    df_ocs = listar_pedidos()
    if not df_ocs.empty:
        st.dataframe(df_ocs[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Obs"]], use_container_width=True, hide_index=True)
        st.divider()
        c1, c2, c3 = st.columns([2,1,1])
        sel_oc = c1.selectbox("Selecione OC:", df_ocs["ID"].unique())
        if sel_oc:
            ns = c2.selectbox("Novo Status", ["Pendente", "Aprovado", "Enviado", "Recebido", "Cancelado"])
            if c2.button("✔️ Atualizar"): atualizar_status(sel_oc, ns); st.success("OK!"); time.sleep(1); st.rerun()
            if c3.button("🗑️ Excluir"): excluir_pedido_db(sel_oc); st.warning("Excluído"); time.sleep(1); st.rerun()
            
            row = df_ocs[df_ocs["ID"] == sel_oc].iloc[0]
            with st.expander("Detalhes", expanded=True):
                itens = row.get("Dados_Completos")
                if isinstance(itens, list) and itens:
                    df_it = pd.DataFrame(itens)
                    df_it["Total"] = (df_it["qtd"].astype(float)*df_it["valor_unit"].astype(float))
                    st.dataframe(df_it, use_container_width=True, hide_index=True)

# --- TAB 6: ALOCAÇÃO ---
with tab6:
    st.header("📦 Alocação (JCA vs ALIVVIA)")
    ra, rj = st.session_state.get("resultado_ALIVVIA"), st.session_state.get("resultado_JCA")
    if ra is not None and rj is not None:
        try:
            df_A = ra[["SKU", "Vendas_Total_60d", "Estoque_Fisico"]].rename(columns={"Vendas_Total_60d": "V_A", "Estoque_Fisico": "E_A"})
            df_J = rj[["SKU", "Vendas_Total_60d", "Estoque_Fisico"]].rename(columns={"Vendas_Total_60d": "V_J", "Estoque_Fisico": "E_J"})
            base = pd.merge(df_A, df_J, on="SKU", how="outer").fillna(0)
            sku = st.selectbox("SKU:", ["Selecione"] + base["SKU"].unique().tolist())
            if sku != "Selecione":
                r = base[base["SKU"]==sku].iloc[0]
                c1,c2,c3 = st.columns(3)
                c1.metric("Vendas A", int(r["V_A"])); c2.metric("Vendas J", int(r["V_J"])); c3.metric("Estoque Total", int(r["E_A"]+r["E_J"]))
                buy = st.number_input("Qtd Compra:", min_value=1, value=500)
                tot_v = r["V_A"]+r["V_J"]
                p_A = r["V_A"]/tot_v if tot_v > 0 else 0.5
                st.write(f"**Sugestão:** Alivvia: {int(buy*p_A)} | JCA: {int(buy*(1-p_A))}")
        except: st.error("Erro alocação.")
    else: st.info("Calcule ambas as empresas.")