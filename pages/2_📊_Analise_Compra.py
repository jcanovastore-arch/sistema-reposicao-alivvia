import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras")

with st.sidebar:
    st.header("⚙️ Parâmetros")
    dias_h = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    cresc = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Filtros")
    f_sku = st.text_input("Filtrar SKU").strip().upper()
    
    if st.button("🔄 Recalcular", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

@st.cache_data
def carregar_dados(d, c, l):
    analises = {}
    for empresa in ["ALIVVIA", "JCA"]:
        df_res = calcular_reposicao(empresa, d, c, l)
        if df_res is not None:
            analises[empresa] = df_res
    return analises

resultados = carregar_dados(dias_h, cresc, lead)

# A LISTA EXATA QUE VOCÊ DETERMINOU
colunas_exigidas = [
    "SKU", "Fornecedor", "Preço de custo", "Vendas full", 
    "vendas Shopee", "Estoque full", "Estoque fisico", 
    "Compra sugerida", "Valor total da compra sugerida"
]

if not resultados:
    st.warning("⚠️ Sem dados. Carregue o catálogo e os arquivos primeiro.")
else:
    for emp, df in resultados.items():
        # Blindagem: Se o cálculo retornar None ou algo errado, pula para não travar
        if df is None or df.empty:
            continue
            
        with st.expander(f"📦 Resultado {emp}", expanded=True):
            # Filtro SKU
            if f_sku:
                df = df[df['SKU'].str.contains(f_sku, na=False)]
            
            # Filtro Fornecedor
            lista_forn = sorted([str(x) for x in df['Fornecedor'].unique() if x != 0 and pd.notna(x)])
            sel_forn = st.multiselect(f"Filtrar Fornecedor ({emp})", lista_forn)
            
            if sel_forn:
                df = df[df['Fornecedor'].isin(sel_forn)]

            # AQUI ESTAVA O ERRO: Agora garantimos que as colunas existem
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
            
            invest = df_final["Valor total da compra sugerida"].sum()
            st.markdown(f"**Total Investimento {emp}:** R$ {invest:,.2f}")