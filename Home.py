import streamlit as st
import time
from src.catalogo_loader import load_catalogo_padrao # Importa a nova função de logic.py

# --- Configurações Iniciais e Session State (Mantenha o que você já tinha) ---
st.set_page_config(
    page_title="Reposição Fácil", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# Inicializa o estado para limpar o uploader (Corrigimos o loop)
if 'upload_counter' not in st.session_state:
    st.session_state['upload_counter'] = 0

# Inicializa o estado do catálogo
if 'catalogo_dados' not in st.session_state:
    st.session_state['catalogo_dados'] = None

# --- Sidebar ---
st.sidebar.title("Reposição Rápida")
st.sidebar.markdown("---")


# --- Bloco do Catálogo na Sidebar (CORREÇÃO DE ACESSO A BASE) ---
st.sidebar.subheader("Padrão KITS/CATALOGO")

# Mostra o status atual
if st.session_state['catalogo_dados'] is not None:
    st.sidebar.success("KITS/CATALOGO carregado!")
else:
    st.sidebar.warning("Carregamento pendente.")

# Botão para carregar os dados
if st.sidebar.button("⬇️ Carregar Padrão KITS/CATALOGO"):
    dados = load_catalogo_padrao()
    if dados:
        st.session_state['catalogo_dados'] = dados
        st.rerun() # Recarrega para que o status mude para "carregado"


# --- Conteúdo Principal (Adapte conforme sua página inicial) ---

st.header("Seja Bem-vindo ao Sistema de Reposição")
st.markdown("Use a barra lateral para navegar:")
st.info("1. Vá para **'Uploads'** e envie os arquivos base da semana.")
st.info("2. Clique em **'Carregar Padrão KITS/CATALOGO'** na sidebar.")
st.info("3. Vá para **'Calculadora de Reposição'** para gerar a compra final.")

# --- Código para teste da função calcular_reposicao (Opcional) ---
# if st.button("Testar Cálculo (Apenas Debug)"):
#     resultado = calcular_reposicao("ALIVVIA")
#     if resultado is not None:
#         st.dataframe(resultado.head())