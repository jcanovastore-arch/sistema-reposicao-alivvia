import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras Integrado")

# --- FILTROS GLOBAIS (Controlam as duas empresas) ---
with st.sidebar:
    st.header("⚙️ Parâmetros de Compra")
    dias_h = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    cresc = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Filtros Unificados")
    f_sku = st.text_input("Filtrar SKU (Global)").strip().upper()
    
    # Criamos uma lista de fornecedores baseada nos dados carregados
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

# Colunas na ordem solicitada, incluindo os novos campos de valor
colunas_exigidas = [
    "SKU", "Fornecedor", "Preço de custo", 
    "Vendas full", "vendas Shopee", 
    "Estoque full (Un)", "Valor Estoque Full",
    "Estoque fisico (Un)", "Valor Estoque Fisico",
    "Compra sugerida", "Valor total da compra sugerida"
]

if not resultados["ALIVVIA"] and not resultados["JCA"]:
    st.warning("⚠️ Sem dados. Verifique os arquivos no gerenciador.")
else:
    # FILTRO DE FORNECEDOR GLOBAL
    todos_forn = []
    for df in resultados.values():
        if df is not None: todos_forn.extend(df['Fornecedor'].unique())
    lista_forn_global = sorted([str(x) for x in set(todos_forn) if x != 0 and pd.notna(x)])
    
    with st.sidebar:
        sel_forn_global = st.multiselect("Filtrar Fornecedor (Global)", lista_forn_global)

    # EXIBIÇÃO DAS DUAS EMPRESAS (ABERTAS)
    for emp in ["ALIVVIA", "JCA"]:
        df = resultados[emp]
        if df is None or df.empty:
            st.error(f"Dados da {emp} não encontrados.")
            continue
        
        st.subheader(f"🏢 Empresa: {emp}")
        
        # Aplicar Filtros Globais
        if f_sku:
            df = df[df['SKU'].str.contains(f_sku, na=False)]
        if sel_forn_global:
            df = df[df['Fornecedor'].isin(sel_forn_global)]

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
        
        # Totais por empresa
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Total Estoque Full {emp}", f"R$ {df_final['Valor Estoque Full'].sum():,.2f}")
        c2.metric(f"Total Estoque Físico {emp}", f"R$ {df_final['Valor Estoque Fisico'].sum():,.2f}")
        c3.metric(f"Total Compra {emp}", f"R$ {df_final['Valor total da compra sugerida'].sum():,.2f}")
        st.divider()