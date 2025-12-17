import streamlit as st
import time
from src.catalogo_loader import load_catalogo_padrao

st.set_page_config(page_title="Reposição Fácil", layout="wide", initial_sidebar_state="expanded")

# Inicializa as variáveis de memória se não existirem
if 'catalogo_dados' not in st.session_state:
    st.session_state['catalogo_dados'] = None
if 'catalogo_carregado' not in st.session_state:
    st.session_state['catalogo_carregado'] = False

st.sidebar.title("Reposição Rápida")
st.sidebar.markdown("---")

# --- Status Visual na Sidebar ---
if st.session_state['catalogo_carregado']:
    st.sidebar.success("✅ CATALOGO/KITS Carregados")
else:
    st.sidebar.warning("⚠️ Carregamento Pendente")

# --- O BOTÃO QUE RESOLVE O PROBLEMA ---
if st.sidebar.button("⬇️ Carregar Padrão KITS/CATALOGO", type="primary"):
    with st.sidebar.status("Conectando ao Google Sheets...", expanded=False) as status:
        dados = load_catalogo_padrao()
        if dados:
            # SALVA NAS DUAS VARIÁVEIS PARA A PÁGINA DE ANÁLISE ENXERGAR
            st.session_state['catalogo_dados'] = dados
            st.session_state['catalogo_carregado'] = True
            status.update(label="Carga concluída!", state="complete", expanded=False)
            st.toast("Dados prontos para análise!")
            time.sleep(1)
            st.rerun()
        else:
            st.sidebar.error("Erro ao acessar o Drive.")

st.sidebar.markdown("---")
st.header("🚀 Sistema de Reposição")
st.info("Após o check verde na esquerda, vá para 'Análise Compra'.")