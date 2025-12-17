import os
import pandas as pd
import streamlit as st
import time
import datetime as dt
import re 
import io 
import numpy as np 
import requests
from unidecode import unidecode
from typing import Optional

# Configurações
DEFAULT_SHEET_LINK = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/edit?usp=sharing"
STORAGE_DIR = ".streamlit/uploaded_files_cache"
if not os.path.exists(STORAGE_DIR): os.makedirs(STORAGE_DIR, exist_ok=True)

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== 1. UTILS E FORMATAÇÃO =====================

def format_br_currency(val):
    if pd.isna(val): return "R$ 0,00"
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_br_int(val):
    if pd.isna(val): return "0"
    return f"{int(val):,}".replace(",", ".")

def norm_sku(x):
    if pd.isna(x): return ""
    return str(x).strip().upper()

def norm_header(s):
    s = str(s).strip().lower()
    s = unidecode(s)
    for ch in [" ", "(", ")", ".", "-", "/"]:
        s = s.replace(ch, "_")
    return s

def br_to_float(x):
    if pd.isna(x): return 0.0
    if isinstance(x, (int, float)): return float(x)
    s = str(x).strip()
    s = s.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try: return float(s)
    except: return 0.0

# ===================== 2. FUNÇÕES DE DADOS (CORREÇÃO DO ERRO) =====================

class Catalogo:
    def __init__(self, df_cat, df_kits):
        self.catalogo_simples = df_cat
        self.kits_reais = df_kits

def _carregar_padrao_de_content(content_bytes) -> Catalogo:
    """Processa o Excel de Padrão de Produtos e separa Kits de Produtos Simples."""
    try:
        xls = pd.read_excel(io.BytesIO(content_bytes), sheet_name=None)
        
        sheet_prod = next((k for k in xls.keys() if "prod" in k.lower()), None)
        sheet_kits = next((k for k in xls.keys() if "kit" in k.lower()), None)
        
        df_prod = xls[sheet_prod] if sheet_prod else pd.DataFrame()
        df_kits = xls[sheet_kits] if sheet_kits else pd.DataFrame()
        
        df_prod.columns = [norm_header(c) for c in df_prod.columns]
        df_kits.columns = [norm_header(c) for c in df_kits.columns]
        
        if "sku" in df_prod.columns: df_prod = df_prod.rename(columns={"sku": "component_sku"})
        if "codigo" in df_prod.columns: df_prod = df_prod.rename(columns={"codigo": "component_sku"})
        
        if "sku_do_kit" in df_kits.columns: df_kits = df_kits.rename(columns={"sku_do_kit": "kit_sku"})
        if "sku_componente" in df_kits.columns: df_kits = df_kits.rename(columns={"sku_componente": "component_sku"})
        
        if "component_sku" in df_prod.columns:
            df_prod["component_sku"] = df_prod["component_sku"].apply(norm_sku)
            
        if "kit_sku" in df_kits.columns and "component_sku" in df_kits.columns:
            df_kits["kit_sku"] = df_kits["kit_sku"].apply(norm_sku)
            df_kits["component_sku"] = df_kits["component_sku"].apply(norm_sku)
            
        return Catalogo(df_prod, df_kits)
    except Exception as e:
        st.error(f"Erro ao processar Padrão de Produtos: {e}")
        return Catalogo(pd.DataFrame(), pd.DataFrame())

def carregar_padrao_local_ou_sheets(link_sheets):
    """
    Tenta carregar do arquivo local, se não existir, baixa do Sheets.
    DEFINIDA LOCALMENTE PARA EVITAR O ERRO 'NOT DEFINED'.
    """
    try:
        sheet_id = link_sheets.split("/d/")[1].split("/")[0]
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        response = requests.get(url)
        response.raise_for_status()
        return _carregar_padrao_de_content(response.content), "Google Sheets"
    except Exception as e:
        raise Exception(f"Falha ao baixar do Sheets: {e}")

# ===================== 3. LEITURA INTELIGENTE DE ARQUIVOS =====================

def encontrar_cabecalho_e_ler(file_bytes, filename) -> pd.DataFrame:
    try:
        is_csv = filename.lower().endswith(".csv")
        if is_csv:
            try: df_raw = pd.read_csv(io.BytesIO(file_bytes), header=None, nrows=20, sep=None, engine='python')
            except: df_raw = pd.read_csv(io.BytesIO(file_bytes), header=None, nrows=20)
        else:
            df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None, nrows=20)

        header_idx = -1
        keywords = ["sku", "codigo", "produto", "anuncio", "id produto"]
        for idx, row in df_raw.iterrows():
            row_str = " ".join([str(x).lower() for x in row.values])
            if any(k in row_str for k in keywords):
                header_idx = idx
                break
        
        if header_idx == -1: header_idx = 0
        
        if is_csv: df = pd.read_csv(io.BytesIO(file_bytes), header=header_idx, sep=None, engine='python')
        else: df = pd.read_excel(io.BytesIO(file_bytes), header=header_idx)
        return df
    except Exception as e:
        st.error(f"Erro ao ler {filename}: {e}")
        return pd.DataFrame()

def mapear_colunas_inteligente(df, tipo):
    df.columns = [norm_header(c) for c in df.columns]
    cols = df.columns
    rename_map = {}
    
    # --- FULL (ML) ---
    if tipo == "FULL":
        if "sku" in cols: rename_map["sku"] = "SKU"
        elif "codigo_sku" in cols: rename_map["codigo_sku"] = "SKU"
        
        col_vendas = next((c for c in cols if "vendas_qtd" in c), None)
        if col_vendas: rename_map[col_vendas] = "Vendas_Full"
        
        col_est = next((c for c in cols if "estoque_atual" in c), None)
        if col_est: rename_map[col_est] = "Estoque_Full"

    # --- VENDAS EXTERNAS (Shopee/Outros) ---
    elif tipo == "VENDAS_EXT":
        if "sku" in cols: rename_map["sku"] = "SKU"
        col_qtd = next((c for c in cols if "unidades" in c or "qtd" in c or "quantidade" in c), None)
        if col_qtd: rename_map[col_qtd] = "Vendas_Ext"

    # --- ESTOQUE FISICO ---
    elif tipo == "FISICO":
        col_sku = next((c for c in cols if "codigo" in c and "sku" in c), None)
        if not col_sku: col_sku = next((c for c in cols if "sku" in c), None)
        if col_sku: rename_map[col_sku] = "SKU"
        
        col_est = next((c for c in cols if "estoque_disponivel" in c), None)
        if not col_est: col_est = next((c for c in cols if "estoque_atual" in c), None)
        if col_est: rename_map[col_est] = "Estoque_Fisico"
        
        col_preco = next((c for c in cols if "preco" in c), None)
        if col_preco: rename_map[col_preco] = "Preco"

    df = df.rename(columns=rename_map)
    if "SKU" in df.columns: df["SKU"] = df["SKU"].apply(norm_sku)
    for c in ["Vendas_Full", "Vendas_Ext", "Estoque_Full", "Estoque_Fisico", "Preco"]:
        if c in df.columns: df[c] = df[c].apply(br_to_float)
    return df

# ===================== 4. LÓGICA DE CÁLCULO =====================

def calcular_necessidade(full_df, ext_df, fis_df, catalogo: Catalogo, dias_horizonte, cresc_pct, lead_time):
    base = full_df.copy()
    if "SKU" not in base.columns: return pd.DataFrame()

    if "Vendas_Full" not in base.columns: base["Vendas_Full"] = 0.0
    if "Estoque_Full" not in base.columns: base["Estoque_Full"] = 0.0

    if ext_df is not None and not ext_df.empty and "SKU" in ext_df.columns:
        ext_clean = ext_df[["SKU", "Vendas_Ext"]].groupby("SKU", as_index=False).sum()
        base = base.merge(ext_clean, on="SKU", how="outer").fillna(0)
    else:
        base["Vendas_Ext"] = 0.0

    if fis_df is not None and not fis_df.empty and "SKU" in fis_df.columns:
        cols_fis = ["SKU", "Estoque_Fisico", "Preco"]
        fis_clean = fis_df[[c for c in cols_fis if c in fis_df.columns]].groupby("SKU", as_index=False).sum(numeric_only=True)
        if "Preco" in fis_df.columns:
             p_map = fis_df.groupby("SKU")["Preco"].max()
             fis_clean["Preco"] = fis_clean["SKU"].map(p_map)
        base = base.merge(fis_clean, on="SKU", how="left").fillna(0)
    else:
        base["Estoque_Fisico"] = 0.0
        base["Preco"] = 0.0
    
    for c in ["Vendas_Full", "Vendas_Ext", "Estoque_Full", "Estoque_Fisico", "Preco"]:
        if c in base.columns: base[c] = base[c].fillna(0)

    base["Vendas_Total_60d"] = base["Vendas_Full"] + base["Vendas_Ext"]
    base["Venda_Media_Dia"] = base["Vendas_Total_60d"] / 60.0
    
    fator_cresc = 1 + (cresc_pct / 100.0)
    base["Venda_Media_Dia"] = base["Venda_Media_Dia"] * fator_cresc
    
    base["Necessidade_Total"] = base["Venda_Media_Dia"] * (dias_horizonte + lead_time)
    base["Estoque_Total"] = base["Estoque_Full"] + base["Estoque_Fisico"]
    
    base["Compra_Sugerida"] = (base["Necessidade_Total"] - base["Estoque_Total"]).apply(np.ceil).clip(lower=0)
    base["Valor_Compra_R$"] = base["Compra_Sugerida"] * base["Preco"]
    
    return base.sort_values("Compra_Sugerida", ascending=False)

# ===================== 5. INTERFACE DO USUÁRIO =====================

if "catalogo_df" not in st.session_state: st.session_state.catalogo_df = None
if "kits_df" not in st.session_state: st.session_state.kits_df = None
if "pedido_ativo" not in st.session_state: st.session_state.pedido_ativo = {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}

for emp in ["ALIVVIA", "JCA"]:
    if emp not in st.session_state: st.session_state[emp] = {}
    for ft in ["FULL", "VENDAS_EXT", "ESTOQUE"]:
        if ft not in st.session_state[emp]: st.session_state[emp][ft] = {"name": None, "bytes": None, "timestamp": None}

with st.sidebar:
    st.header("⚙️ Parâmetros")
    h_p = st.selectbox("Horizonte (Dias)", [30, 60, 90], index=1)
    g_p = st.number_input("Crescimento %", value=0.0)
    lt_p = st.number_input("Lead Time (Dias)", value=0)
    st.divider()
    st.subheader("📂 Dados Mestre")
    
    if st.button("🔄 Baixar Sheets (Padrão)"):
        try:
            c, origem = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples
            st.session_state.kits_df = c.kits_reais
            st.success(f"Carregado via {origem}!")
        except Exception as e: st.error(f"Erro: {e}")

    up_m = st.file_uploader("Ou Excel Manual", type=["xlsx"])
    if up_m:
        c = _carregar_padrao_de_content(up_m.getvalue())
        st.session_state.catalogo_df = c.catalogo_simples
        st.session_state.kits_df = c.kits_reais
        st.success("Ok!")

st.title("Reposição Logística — Alivvia (V43 Stable)")

tab1, tab2, tab3, tab4 = st.tabs(["📂 Uploads", "🔍 Análise", "🚛 Cruzar PDF/Excel", "📝 Pedido"])

# --- TAB 1: UPLOADS ---
with tab1:
    c1, c2 = st.columns(2)
    def render_upload(emp, col):
        with col:
            st.markdown(f"### {emp}")
            
            f_full = st.file_uploader(f"1. Relatório FULL (ML) - {emp}", type=["xlsx", "csv"], key=f"u_{emp}_full")
            if f_full:
                st.session_state[emp]["FULL"] = {"bytes": f_full.getvalue(), "name": f_full.name, "timestamp": str(dt.datetime.now())}
                st.success("Full Carregado!")
            
            f_ext = st.file_uploader(f"2. Vendas Externas (Shopee) - {emp}", type=["xlsx", "csv"], key=f"u_{emp}_ext")
            if f_ext:
                st.session_state[emp]["VENDAS_EXT"] = {"bytes": f_ext.getvalue(), "name": f_ext.name, "timestamp": str(dt.datetime.now())}
                st.success("Vendas Ext Carregado!")

            f_fis = st.file_uploader(f"3. Estoque Físico - {emp}", type=["xlsx", "csv"], key=f"u_{emp}_fis")
            if f_fis:
                st.session_state[emp]["ESTOQUE"] = {"bytes": f_fis.getvalue(), "name": f_fis.name, "timestamp": str(dt.datetime.now())}
                st.success("Estoque Carregado!")

    render_upload("ALIVVIA", c1)
    render_upload("JCA", c2)

# --- TAB 2: ANÁLISE ---
with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        def processar(emp):
            s = st.session_state[emp]
            if not s["FULL"]["bytes"]: return st.warning(f"Falta arquivo FULL de {emp}")
            
            df_full_raw = encontrar_cabecalho_e_ler(s["FULL"]["bytes"], s["FULL"]["name"])
            df_full = mapear_colunas_inteligente(df_full_raw, "FULL")
            
            df_ext = pd.DataFrame()
            if s["VENDAS_EXT"]["bytes"]:
                df_ext_raw = encontrar_cabecalho_e_ler(s["VENDAS_EXT"]["bytes"], s["VENDAS_EXT"]["name"])
                df_ext = mapear_colunas_inteligente(df_ext_raw, "VENDAS_EXT")
                
            df_fis = pd.DataFrame()
            if s["ESTOQUE"]["bytes"]:
                df_fis_raw = encontrar_cabecalho_e_ler(s["ESTOQUE"]["bytes"], s["ESTOQUE"]["name"])
                df_fis = mapear_colunas_inteligente(df_fis_raw, "FISICO")
            
            cat = Catalogo(st.session_state.catalogo_df, st.session_state.kits_df)
            res = calcular_necessidade(df_full, df_ext, df_fis, cat, h_p, g_p, lt_p)
            st.session_state[f"res_{emp}"] = res
            st.success(f"Cálculo {emp} OK!")

        if c1.button("CALCULAR ALIVVIA"): processar("ALIVVIA")
        if c2.button("CALCULAR JCA"): processar("JCA")
        
        st.divider()
        f_sku = st.text_input("Filtrar SKU:").upper()
        
        for emp in ["ALIVVIA", "JCA"]:
            if f"res_{emp}" in st.session_state:
                st.markdown(f"### 📊 Resultado {emp}")
                df = st.session_state[f"res_{emp}"].copy()
                if f_sku: df = df[df["SKU"].str.contains(f_sku, na=False)]
                
                c_k1, c_k2, c_k3 = st.columns(3)
                c_k1.metric("💰 Sugestão (R$)", format_br_currency(df["Valor_Compra_R$"].sum()))
                c_k2.metric("📦 Peças Sugeridas", format_br_int(df["Compra_Sugerida"].sum()))
                c_k3.metric("📉 Demanda Total Calc.", format_br_int(df["Necessidade_Total"].sum()))
                
                cols_view = ["SKU", "Vendas_Full", "Vendas_Ext", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Compra_Sugerida", "Preco", "Valor_Compra_R$"]
                df["Selecionar"] = False
                
                edited = st.data_editor(
                    df[["Selecionar"] + [c for c in cols_view if c in df.columns]],
                    hide_index=True,
                    use_container_width=True,
                    key=f"ed_{emp}",
                    column_config={
                        "Selecionar": st.column_config.CheckboxColumn(default=False),
                        "Vendas_Full": st.column_config.NumberColumn("Vendas Full (ML)", format="%d"),
                        "Vendas_Ext": st.column_config.NumberColumn("Vendas Ext (Shopee)", format="%d"),
                        "Vendas_Total_60d": st.column_config.NumberColumn("Total Vendas", format="%d"),
                        "Preco": st.column_config.NumberColumn(format="R$ %.2f"),
                        "Valor_Compra_R$": st.column_config.NumberColumn(format="R$ %.2f")
                    }
                )
                
                if st.button(f"Adicionar ao Pedido ({emp})", key=f"add_{emp}"):
                    sel = edited[edited["Selecionar"]==True]
                    curr = st.session_state.pedido_ativo["itens"]
                    exist = [x["sku"] for x in curr]
                    c = 0
                    for _, r in sel.iterrows():
                        if r["SKU"] not in exist and r["Compra_Sugerida"] > 0:
                            curr.append({"sku": r["SKU"], "qtd": int(r["Compra_Sugerida"]), "valor_unit": float(r["Preco"]), "origem": emp})
                            c+=1
                    st.session_state.pedido_ativo["itens"] = curr
                    st.toast(f"{c} itens adicionados!")

# --- TAB 3: CRUZAMENTO ---
with tab3:
    st.header("Cruzamento Inbound")
    emp_t = st.radio("Empresa:", ["ALIVVIA", "JCA"], horizontal=True)
    f_in = st.file_uploader("Upload Inbound (Excel/CSV)", type=["xlsx", "csv"])
    if f_in and f"res_{emp_t}" in st.session_state:
        df_in_raw = encontrar_cabecalho_e_ler(f_in.getvalue(), f_in.name)
        col_prod = next((c for c in df_in_raw.columns if "PRODUTO" in str(c).upper()), None)
        col_qtd = next((c for c in df_in_raw.columns if "UNIDADES" in str(c).upper()), None)
        
        if col_prod and col_qtd:
            data_in = []
            regex = re.compile(r'SKU:?\s*([\w\-\/\+\.\&]+)', re.IGNORECASE)
            for _, r in df_in_raw.iterrows():
                m = regex.search(str(r[col_prod]))
                if m: data_in.append({"SKU": m.group(1).upper(), "Qtd_Envio": br_to_float(r[col_qtd])})
            df_in = pd.DataFrame(data_in).groupby("SKU", as_index=False).sum()

            df_base = st.session_state[f"res_{emp_t}"].copy()
            merged = df_in.merge(df_base[["SKU", "Estoque_Fisico", "Preco"]], on="SKU", how="left")
            merged["Faltam"] = (merged["Qtd_Envio"] - merged["Estoque_Fisico"].fillna(0)).clip(lower=0)
            merged["Custo"] = merged["Faltam"] * merged["Preco"].fillna(0)
            
            st.dataframe(merged)
            
            if st.button("Add Faltantes ao Pedido"):
                filt = merged[merged["Faltam"] > 0]
                curr = st.session_state.pedido_ativo["itens"]
                exist = [x["sku"] for x in curr]
                for _, r in filt.iterrows():
                    if r["SKU"] not in exist:
                        curr.append({"sku": r["SKU"], "qtd": int(r["Faltam"]), "valor_unit": float(r["Preco"] or 0), "origem": "INBOUND"})
                st.session_state.pedido_ativo["itens"] = curr
                st.success("Adicionado!")
        else:
            st.error("Não encontrei colunas PRODUTO e UNIDADES no Excel do Inbound.")

# --- TAB 4: PEDIDO ---
with tab4:
    st.header("Pedido")
    ped = st.session_state.pedido_ativo
    c1, c2 = st.columns(2)
    ped["fornecedor"] = c1.text_input("Fornecedor", ped["fornecedor"])
    ped["obs"] = c2.text_input("Obs", ped["obs"])
    
    if ped["itens"]:
        df_p = pd.DataFrame(ped["itens"])
        df_p["Total"] = df_p["qtd"]*df_p["valor_unit"]
        ed_p = st.data_editor(df_p, num_rows="dynamic", use_container_width=True)
        st.session_state.pedido_ativo["itens"] = ed_p.to_dict("records")
        st.metric("Total", format_br_currency(ed_p["Total"].sum()))
        
        if st.button("Salvar OC (Simulação)", type="primary"):
             from src.orders_db import salvar_pedido, gerar_numero_oc 
             try:
                nid = gerar_numero_oc("ALIVVIA")
                if salvar_pedido({"id": nid, "empresa": "ALIVVIA/JCA", "fornecedor": ped["fornecedor"], "data_emissao": str(dt.date.today()), "valor_total": ed_p["Total"].sum(), "status": "Pendente", "obs": ped["obs"], "itens": st.session_state.pedido_ativo["itens"]}):
                    st.success(f"OC {nid} Salva!")
                    st.session_state.pedido_ativo["itens"] = []
                    time.sleep(1)
                    st.rerun()
             except Exception as e:
                st.error(f"Erro ao salvar: {e}. Verifique se src.orders_db existe.")