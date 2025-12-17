import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras")

# --- PARÂMETROS E FILTROS NA SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parâmetros")
    dias_horizonte = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    crescimento = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead_time = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Filtros")
    filtro_sku = st.text_input("Filtrar por SKU").strip().upper()
    
    if st.button("🔄 Recalcular", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --- CÁLCULO ---
@st.cache_data
def get_analise(dias, cresc, lead):
    analises = {}
    for emp in ["ALIVVIA", "JCA"]:
        df = calcular_reposicao(emp, dias, cresc, lead)
        if df is not None:
            analises[emp] = df
    return analises

resultados = get_analise(dias_horizonte, crescimento, lead_time)

if not resultados:
    st.warning("Carregue o catálogo na Home e envie os arquivos no Gerenciador.")
else:
    # LISTA DE COLUNAS OBRIGATÓRIAS (NA ORDEM PEDIDA)
    colunas_finais = [
        "SKU", "Fornecedor", "Preço de custo", "Vendas full", 
        "vendas Shopee", "Estoque full", "Estoque fisico", 
        "Compra sugerida", "Valor total da compra sugerida"
    ]

    for emp, df in resultados.items():
        with st.expander(f"📦 Resultado {emp}", expanded=True):
            # Aplicar Filtro de SKU
            if filtro_sku:
                df = df[df['SKU'].str.contains(filtro_sku, na=False)]
            
            # Filtro de Fornecedor dinâmico
            lista_forn = sorted(df['Fornecedor'].unique().tolist())
            fornecedores_sel = st.multiselect(f"Filtrar Fornecedor ({emp})", lista_forn, key=f"forn_{emp}")
            
            if fornecedores_sel:
                df = df[df['Fornecedor'].isin(fornecedores_sel)]

            # Exibição
            df_final = df[colunas_finais].sort_values("Compra sugerida", ascending=False)
            
            st.dataframe(
                df_final,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Preço de custo": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor total da compra sugerida": st.column_config.NumberColumn(format="R$ %.2f")
                }
            )
            
            # Totais
            t_compra = df_final['Valor total da compra sugerida'].sum()
            t_itens = df_final['Compra sugerida'].sum()
            st.markdown(f"**Total de Itens:** {t_itens} | **Investimento Total:** R$ {t_compra:,.2f}")