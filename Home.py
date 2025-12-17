import streamlit as st
import time
# IMPORTAÇÃO CORRIGIDA: Agora vem do arquivo isolado para evitar conflitos
from src.catalogo_loader import load_catalogo_padrao

# --- Configurações Iniciais e Session State ---
st.set_page_config(
    page_title="Reposição Fácil", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# Inicializa o contador para limpar o uploader (upload)
if 'upload_counter' not in st.session_state:
    st.session_state['upload_counter'] = 0

# Inicializa o estado do catálogo (Aqui onde os dados são salvos)
if 'catalogo_dados' not in st.session_state:
    st.session_state['catalogo_dados'] = None
    
# Inicializa o estado 'catalogo_carregado'
if 'catalogo_carregado' not in st.session_state:
    st.session_state['catalogo_carregado'] = False


# --- Sidebar ---
st.sidebar.title("Reposição Rápida")
st.sidebar.markdown("---")


# --- Bloco do Catálogo na Sidebar (FINALIZADO E CORRETO) ---
st.sidebar.subheader("Padrão KITS/CATALOGO")

# Mostra o status atual
if st.session_state['catalogo_dados'] is not None and st.session_state['catalogo_carregado']:
    st.sidebar.success("KITS/CATALOGO carregado!")
else:
    st.sidebar.warning("Carregamento pendente.")

# Botão para carregar os dados
if st.sidebar.button("⬇️ Carregar Padrão KITS/CATALOGO"):
    # Carrega os dados usando a função importada
    dados = load_catalogo_padrao() 
    if dados:
        st.session_state['catalogo_dados'] = dados
        # O rerun é o que faz o status mudar de Pendente para Carregado.
        st.rerun() 
st.sidebar.markdown("---") # Linha para separar do resto da sidebar


# --- Conteúdo Principal (A página Home) ---
st.header("Seja Bem-vindo ao Sistema de Reposição")
st.markdown("""
Use a barra lateral e os passos abaixo para garantir a análise correta:

1.  **Carregar Catálogo:** Clique no botão **'⬇️ Carregar Padrão KITS/CATALOGO'** na barra lateral. O status deve mudar para "KITS/CATALOGO carregado!".
2.  **Enviar Arquivos:** Vá para a página **'Uploads'** e envie os arquivos base da semana (Full, Ext, Físico).
3.  **Análise Final:** Vá para a página **'Análise Compra'** para gerar a compra final.
""")

# --- Fim do Arquivo ---