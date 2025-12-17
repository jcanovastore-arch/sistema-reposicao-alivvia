import streamlit as st
from src.logic import calcular_reposicao
from src.data import carregar_bases_para_calculo
from src import utils
import pandas as pd 
import numpy as np

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Análise e Sugestão de Reposição")

# --- 1. VERIFICAÇÃO DE DADOS BASE ---
dados_catalogo = st.session_state.get('catalogo_dados')

if dados_catalogo is None:
    st.info("⚠️ O Catálogo Padrão não foi carregado. Volte na Home e clique em 'Carregar Padrão'.")
    st.stop()

# --- 2. FUNÇÃO DE EXECUÇÃO ---
@st.cache_data(ttl=60) 
def executar_calculo(empresa):
    bases = carregar_bases_para_calculo(empresa)
    if bases is None:
        return None
    
    # Envia os dados descompactados para a lógica
    df_res = calcular_reposicao(
        bases["df_full"],
        bases["df_fisico"],
        bases["df_ext"],
        bases["catalogo_kits"],
        bases["catalogo_simples"],
        empresa
    )
    return df_res

# --- 3. INTERFACE ---
c1, c2 = st.columns(2)
with c1:
    if st.button(f"🚀 CALCULAR ALIVVIA", use_container_width=True):
        st.session_state["res_ALIVVIA"] = executar_calculo("ALIVVIA")
with c2:
    if st.button(f"🚀 CALCULAR JCA", use_container_width=True):
        st.session_state["res_JCA"] = executar_calculo("JCA")

st.divider()

# Escolha de qual resultado visualizar
empresa_visualizar = st.radio("Visualizar resultado de:", ["ALIVVIA", "JCA"], horizontal=True)
df_reposicao_geral = st.session_state.get(f"res_{empresa_visualizar}")

if df_reposicao_geral is not None:
    # Filtros
    f1, f2 = st.columns([1, 1])
    fornecedores = sorted(df_reposicao_geral['Fornecedor'].dropna().unique())
    fornecedor_sel = f1.multiselect("Filtrar Fornecedor:", options=fornecedores, default=fornecedores)
    sku_sel = f2.text_input("Buscar SKU:").upper()

    # Aplica filtros
    df_filtrado = df_reposicao_geral[df_reposicao_geral['Fornecedor'].isin(fornecedor_sel)]
    if sku_sel:
        df_filtrado = df_filtrado[df_filtrado['SKU'].str.contains(sku_sel, na=False)]

    # Exibe
    st.subheader(f"Sugestão de Compra: {empresa_visualizar}")
    df_compra = df_filtrado[df_filtrado['Compra_Sugerida'] > 0].copy()
    
    if df_compra.empty:
        st.success("Estoque em dia! Nenhuma compra necessária para estes filtros.")
    else:
        st.metric("Total Investimento Sugerido", utils.format_br_currency(df_compra['Valor_Sugerido_R$'].sum()))
        st.dataframe(utils.style_df_compra(df_compra), use_container_width=True)
else:
    st.info("Clique no botão 'CALCULAR' acima para processar os dados.")