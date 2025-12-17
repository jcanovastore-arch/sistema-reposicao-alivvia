import streamlit as st
import time
from src.catalogo_loader import load_catalogo_padrao

st.set_page_config(page_title="Reposição Fácil", layout="wide", initial_sidebar_state="expanded")

# Inicializa as variáveis de memória (Essencial para as outras abas verem os dados)
if 'catalogo_dados' not in st.session_state:
    st.session_state['catalogo_dados'] = None
if 'catalogo_carregado' not in st.session_state:
    st.session_state['catalogo_carregado'] = False

st.sidebar.title("Reposição Rápida")
st.sidebar.markdown("---")

# Status visual
if st.session_state['catalogo_carregado']:
    st.sidebar.success("✅ CATALOGO/KITS Carregados")
else:
    st.sidebar.warning("⚠️ Carregamento Pendente")

# Botão de Carga
if st.sidebar.button("⬇️ Carregar Padrão KITS/CATALOGO", type="primary"):
    with st.sidebar.status("Conectando ao Google Sheets...", expanded=False) as status:
        # Busca os dados (Lógica congelada no catalogo_loader)
        dados = load_catalogo_padrao()
        
        if dados:
            st.session_state['catalogo_dados'] = dados
            st.session_state['catalogo_carregado'] = True
            status.update(label="Carga concluída!", state="complete", expanded=False)
            st.toast("Catálogo carregado!")
            time.sleep(0.5)
            st.rerun()
        else:
            st.sidebar.error("Falha ao carregar.")

st.header("🚀 Sistema de Reposição")
st.markdown("---")
st.info("Certifique-se de ver o check verde à esquerda antes de ir para a Análise de Compra.")