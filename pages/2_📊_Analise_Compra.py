import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras Integrado")

# --- TRAVA DE SEGURANÇA ---
if not st.session_state.get('catalogo_carregado'):
    st.error("⚠️ O Catálogo não foi carregado. Por favor, volte à página Home e clique em 'Carregar Padrão'.")
    st.stop()

# --- FILTROS GLOBAIS NA SIDEBAR ---
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
def carregar_resultados(d, c, l):
    # Chama a lógica congelada para ambas as empresas
    return {
        "ALIVVIA": calcular_reposicao("ALIVVIA", d, c, l),
        "JCA": calcular_reposicao("JCA", d, c, l)
    }

resultados = carregar_resultados(dias_h, cresc, lead)

# Colunas exatas que você exigiu
colunas_exigidas = [
    "SKU", "Fornecedor", "Preço de custo", 
    "Vendas full", "vendas Shopee", 
    "Estoque full (Un)", "Valor Estoque Full",
    "Estoque fisico (Un)", "Valor Estoque Fisico",
    "Compra sugerida", "Valor total da compra sugerida"
]

# Lógica para Filtro de Fornecedor Global
todos_forn = []
for df_temp in resultados.values():
    if df_temp is not None and not df_temp.empty:
        todos_forn.extend(df_temp['Fornecedor'].dropna().unique())
lista_forn_global = sorted([str(x) for x in set(todos_forn) if str(x) not in ["0", "nan", "None"]])

with st.sidebar:
    sel_forn_global = st.multiselect("Filtrar Fornecedor (Global)", lista_forn_global)

# --- EXIBIÇÃO (SEMPRE ABERTA) ---
for emp in ["ALIVVIA", "JCA"]:
    df = resultados.get(emp)
    
    if df is not None and not df.empty:
        st.subheader(f"🏢 Empresa: {emp}")
        
        # Aplicar Filtros
        if f_sku:
            df = df[df['SKU'].str.contains(f_sku, na=False)]
        if sel_forn_global:
            df = df[df['Fornecedor'].isin(sel_forn_global)]

        # Ordenação e Exibição
        df_final = df[colunas_exigidas].sort_values("Compra sugerida", ascending=False)
        
        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Preço de custo": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Estoque Full": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Estoque Fisico": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor total da compra sugerida": st.column_config.NumberColumn(format="R$ %.2f")
            }
        )
        
        # Resumo Financeiro
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Valoração Full {emp}", f"R$ {df_final['Valor Estoque Full'].sum():,.2f}")
        c2.metric(f"Valoração Físico {emp}", f"R$ {df_final['Valor Estoque Fisico'].sum():,.2f}")
        c3.metric(f"Total Sugerido {emp}", f"R$ {df_final['Valor total da compra sugerida'].sum():,.2f}")
        st.divider()