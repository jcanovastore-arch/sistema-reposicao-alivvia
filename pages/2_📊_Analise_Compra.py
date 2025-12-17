import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras Integrado")

# --- VERIFICAÇÃO DE SEGURANÇA ---
# Se a Home carregou, ele entra aqui.
if not st.session_state.get('catalogo_carregado') or st.session_state.get('catalogo_dados') is None:
    st.error("⚠️ O Catálogo não foi detectado. Volte na Home e clique no botão '⬇️ Carregar Padrão'.")
    st.stop()

with st.sidebar:
    st.header("⚙️ Parâmetros")
    dias_h = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    cresc = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Filtros Unificados")
    f_sku = st.text_input("Filtrar SKU (Global)").strip().upper()
    
    if st.button("🔄 Recalcular Tudo", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

@st.cache_data
def carregar_dados_unificados(d, c, l):
    return {
        "ALIVVIA": calcular_reposicao("ALIVVIA", d, c, l),
        "JCA": calcular_reposicao("JCA", d, c, l)
    }

resultados = carregar_dados_unificados(dias_h, cresc, lead)

# Colunas que você determinou (CONGELADO)
colunas_exigidas = [
    "SKU", "Fornecedor", "Preço de custo", 
    "Vendas full", "vendas Shopee", 
    "Estoque full (Un)", "Valor Estoque Full",
    "Estoque fisico (Un)", "Valor Estoque Fisico",
    "Compra sugerida", "Valor total da compra sugerida"
]

# --- LÓGICA DE EXIBIÇÃO (MANTIDA) ---
# Filtro Global de Fornecedor
todos_forn = []
for emp in resultados:
    df_temp = resultados[emp]
    if df_temp is not None and not df_temp.empty:
        todos_forn.extend(df_temp['Fornecedor'].dropna().unique())
lista_forn_global = sorted([str(x) for x in set(todos_forn) if str(x) not in ["0", "nan", "None"]])

with st.sidebar:
    sel_forn_global = st.multiselect("Filtrar Fornecedor (Global)", lista_forn_global)

for emp in ["ALIVVIA", "JCA"]:
    df = resultados.get(emp)
    if df is not None and not df.empty:
        st.subheader(f"🏢 Empresa: {emp}")
        if f_sku:
            df = df[df['SKU'].str.contains(f_sku, na=False)]
        if sel_forn_global:
            df = df[df['Fornecedor'].isin(sel_forn_global)]

        df_final = df[colunas_exigidas].sort_values("Compra sugerida", ascending=False)
        st.dataframe(df_final, use_container_width=True, hide_index=True)
        st.divider()