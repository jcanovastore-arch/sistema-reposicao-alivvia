import streamlit as st
from src.logic import calcular_reposicao # Esta importação AGORA vai funcionar
from src.data import carregar_bases_para_calculo 
import pandas as pd 

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Análise e Sugestão de Reposição")

# --- CORREÇÃO DE Attribute ERROR (VERIFICAÇÃO SEGURA) ---
# Se os dados não foram carregados pelo botão do Home.py, o Streamlit para aqui.
dados_catalogo = st.session_state.get('catalogo_dados')

if dados_catalogo is None:
    st.info("⚠️ O Catálogo Padrão não foi carregado. Por favor, volte para a página principal e clique no botão '⬇️ Carregar Padrão KITS/CATALOGO' na barra lateral.")
    st.stop()
# --- FIM DA CORREÇÃO ---

st.header("1. Seleção da Empresa")
empresa_selecionada = st.selectbox(
    "Escolha a empresa para análise:",
    options=["ALIVVIA", "JCA"]
)

if st.button("Executar Análise de Reposição"):
    
    # Carrega todas as bases (Uploads do Supabase + Catálogo do Drive)
    bases = carregar_bases_para_calculo(empresa_selecionada)
    
    if bases is not None:
        st.subheader(f"Processando dados de {empresa_selecionada}...")

        # Chama a função de cálculo (que está em src/logic.py)
        df_reposicao = calcular_reposicao(empresa_selecionada)

        if df_reposicao is not None:
            st.success("✅ Análise e Sugestão de Reposição Concluída!")
            
            # Exemplo de exibição do resultado
            st.subheader("Sugestão de Compra")
            st.dataframe(df_reposicao) # Mostra o DataFrame de saída
        else:
            st.error("❌ Não foi possível gerar a sugestão. Verifique os uploads.")