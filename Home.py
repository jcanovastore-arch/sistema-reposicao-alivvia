import streamlit as st

st.set_page_config(page_title="Sistema Compras", layout="wide")

st.title("🏠 Sistema de Compras e Reposição")

# INICIALIZAÇÃO GLOBAL DE VARIÁVEIS (Para não perder dados ao trocar de página)
if "pedido" not in st.session_state:
    st.session_state.pedido = []

if "catalogo" not in st.session_state:
    st.session_state.catalogo = None

st.info("👈 Use o menu lateral para navegar entre as ferramentas.")
st.markdown("""
- **1. Uploads:** Envie os arquivos para a nuvem (Supabase).
- **2. Análise:** Calcule sugestão de compras separando Full/Externo.
- **3. Inbound:** Cruza Nota Fiscal/PDF com Estoque Físico.
- **4. Editor OC:** Finalize o pedido com itens selecionados.
- **5. Gestão:** Histórico de pedidos salvos.
- **6. Alocação:** Divida uma compra grande entre as empresas baseado nas vendas.
""")