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

# Inicializa o estado do catálogo (Onde os dados são salvos)
if 'catalogo_dados' not in st.session_state:
    st.session_state['catalogo_dados'] = None
    
# Inicializa o estado 'catalogo_carregado'
if 'catalogo_carregado' not in st.session_state:
    st.session_state['catalogo_carregado'] = False

# --- Sidebar ---
st.sidebar.title("Reposição Rápida")
st.sidebar.markdown("---")

# --- Bloco do Catálogo na Sidebar ---
st.sidebar.subheader("Padrão KITS/CATALOGO")

# Mostra o status atual de forma visual
if st.session_state['catalogo_carregado']:
    st.sidebar.success("✅ CATALOGO/KITS Carregados")
else:
    st.sidebar.warning("⚠️ Carregamento Pendente")

# Botão para carregar os dados
if st.sidebar.button("⬇️ Carregar Padrão KITS/CATALOGO", type="primary"):
    with st.sidebar.status("Conectando ao Drive...", expanded=False) as status:
        # Chama a função que já configuramos com o link padrão
        dados = load_catalogo_padrao() 
        
        if dados:
            st.session_state['catalogo_dados'] = dados
            st.session_state['catalogo_carregado'] = True # AGORA ELE MUDA O STATUS
            status.update(label="Carga concluída!", state="complete", expanded=False)
            st.toast("Catálogo carregado com sucesso!")
            time.sleep(1)
            st.rerun() 
        else:
            st.sidebar.error("Falha na conexão.")

st.sidebar.markdown("---")

# --- Conteúdo Principal (Home Page) ---
st.header("🚀 Seja Bem-vindo ao Sistema de Reposição")

# Layout em colunas para ficar mais profissional para o seu chefe
c1, c2, c3 = st.columns(3)

with c1:
    st.info("**Passo 1**\n\nCarregue o catálogo na barra lateral.")
with c2:
    st.info("**Passo 2**\n\nEnvie os arquivos na aba 'Uploads'.")
with c3:
    st.info("**Passo 3**\n\nVeja o resultado na 'Análise Compra'.")

st.markdown("---")
st.markdown("### Instruções de Uso")
st.write("""
Este sistema cruza os dados do seu **Google Sheets** com os relatórios do **Mercado Livre** e **Shopee** para sugerir compras precisas.
- O catálogo é lido da aba **CATALOGO_SIMPLES**.
- Produtos marcados como **nao_repor** na coluna de status serão ignorados automaticamente.
""")