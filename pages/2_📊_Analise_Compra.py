import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras")

# --- SIDEBAR COM PARÂMETROS E FILTRO DE SKU ---
with st.sidebar:
    st.header("⚙️ Parâmetros")
    dias_horizonte = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    crescimento = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead_time = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Busca Rápida")
    filtro_sku = st.text_input("Filtrar por SKU").strip().upper()
    
    if st.button("🔄 Recalcular", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

@st.cache_data
def get_analise(dias, cresc, lead):
    analises = {}
    for emp in ["ALIVVIA", "JCA"]:
        df = calcular_reposicao(emp, dias, cresc, lead)
        if df is not None:
            analises[emp] = df
    return analises

resultados = get_analise(dias_horizonte, crescimento, lead_time)

# COLUNAS FIXAS EXIGIDAS POR VOCÊ
colunas_exigidas = [
    "SKU", "Fornecedor", "Preço de custo", "Vendas full", 
    "vendas Shopee", "Estoque full", "Estoque fisico", 
    "Compra sugerida", "Valor total da compra sugerida"
]

if not resultados:
    st.warning("⚠️ Carregue o catálogo na Home e faça o upload dos arquivos no Gerenciador.")
else:
    for emp, df in resultados.items():
        # Blindagem: se por algum erro o df vier vazio ou None, não quebra a tela
        if df is None or df.empty:
            st.error(f"Não foi possível processar os dados da {emp}.")
            continue
            
        with st.expander(f"📦 Resultado {emp}", expanded=True):
            # 1. Filtro de SKU (Busca)
            if filtro_sku:
                df = df[df['SKU'].str.contains(filtro_sku, na=False)]
            
            # 2. Filtro de Fornecedor (Multiselect)
            # O dropna() e unique() garantem que não dê erro se houver lixo nos dados
            lista_forn = sorted([str(x) for x in df['Fornecedor'].dropna().unique()])
            fornecedores_sel = st.multiselect(f"Filtrar por Fornecedor ({emp})", lista_forn, key=f"f_{emp}")
            
            if fornecedores_sel:
                df = df[df['Fornecedor'].isin(fornecedores_sel)]

            # Exibição Final
            df_final = df[colunas_exigidas].sort_values("Compra sugerida", ascending=False)
            
            st.dataframe(
                df_final,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Preço de custo": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor total da compra sugerida": st.column_config.NumberColumn(format="R$ %.2f")
                }
            )
            
            total_invest = df_final['Valor total da compra sugerida'].sum()
            st.markdown(f"**Total Investimento {emp}:** R$ {total_invest:,.2f}")