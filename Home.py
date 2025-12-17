import streamlit as st
import time
# IMPORTAÇÃO CORRIGIDA: Usa o arquivo isolado para evitar conflitos
from src.catalogo_loader import load_catalogo_padrao

# --- Configurações Iniciais e Session State ---
st.set_page_config(
    page_title="Reposição Fácil", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# Inicializa o estado do catálogo (Aqui onde os dados são salvos)
if 'catalogo_dados' not in st.session_state:
    st.session_state['catalogo_dados'] = None
    
# Inicializa o estado 'catalogo_carregado'
if 'catalogo_carregado' not in st.session_state:
    st.session_state['catalogo_carregado'] = False


# --- Sidebar ---
st.sidebar.title("Reposição Rápida")
st.sidebar.markdown("---")


# --- Bloco do Catálogo na Sidebar (ESTE BOTÃO DEVE APARECER) ---
st.sidebar.subheader("Padrão KITS/CATALOGO")

# Mostra o status atual
if st.session_state['catalogo_dados'] is not None and st.session_state['catalogo_carregado']:
    st.sidebar.success("KITS/CATALOGO carregado!")
else:
    st.sidebar.warning("Carregamento pendente.")

# Botão para carregar os dados
if st.sidebar.button("⬇️ Carregar Padrão KITS/CATALOGO"):
    dados = load_catalogo_padrao() 
    if dados:
        st.session_state['catalogo_dados'] = dados
        st.rerun() 
st.sidebar.markdown("---")


# --- Conteúdo Principal (Home Page) ---
st.header("Seja Bem-vindo ao Sistema de Reposição")
st.markdown("""
Siga os passos na barra lateral para iniciar a análise de reposição:

1.  **Carregar Catálogo:** Clique no botão **'⬇️ Carregar Padrão KITS/CATALOGO'** na sidebar.
2.  **Enviar Arquivos:** Use a página **'Uploads'** para enviar os arquivos base da semana.
3.  **Análise Final:** Use a página **'Análise Compra'** para gerar a sugestão.
""")