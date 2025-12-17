import streamlit as st
from src.logic import calcular_reposicao
import pandas as pd 

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Reposição")

with st.sidebar:
    st.header("⚙️ Parâmetros")
    dias_horizonte = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    crescimento = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead_time = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    if st.button("🔄 Recalcular", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Função de cache simplificada
@st.cache_data
def calcular_todas_empresas(dias, cresc, lead):
    analises = {}
    for emp in ["ALIVVIA", "JCA"]:
        df = calcular_reposicao(emp, dias, cresc, lead)
        if df is not None:
            analises[emp] = df
    return analises

resultados = calcular_todas_empresas(dias_horizonte, crescimento, lead_time)

if not resultados:
    st.warning("⚠️ Sem dados. Verifique se os arquivos foram enviados e o Catálogo carregado.")
else:
    for emp, df in resultados.items():
        with st.expander(f"📦 Resultado {emp}", expanded=True):
            # Salva no estado para outras páginas usarem
            st.session_state[f"res_{emp}"] = df
            
            # Filtro para não poluir a tela
            df_show = df[(df['Compra_Sugerida'] > 0) | (df['Estoque_Total'] > 0)].copy()
            st.dataframe(df_show, use_container_width=True, hide_index=True)