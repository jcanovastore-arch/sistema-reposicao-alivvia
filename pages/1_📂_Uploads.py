import streamlit as st
import time
from src import storage

st.set_page_config(page_title="Uploads", layout="wide")
st.title("☁️ Gerenciador de Arquivos")

col_alivvia, col_jca = st.columns(2)

def render_file_slot(empresa, label_amigavel, tipo_arquivo):
    """
    Cria um bloco visual para gerenciar um único arquivo.
    Ex: Alivvia -> Full
    """
    # Caminho exato no Supabase
    path_cloud = f"{empresa}/{tipo_arquivo}.xlsx"
    
    st.markdown(f"**{label_amigavel}**")
    
    # 1. Verifica se já existe na nuvem
    existe = storage.file_exists(path_cloud)
    
    if existe:
        # Se existe, mostra caixa verde com botão de excluir
        c1, c2 = st.columns([0.8, 0.2])
        c1.success("✅ Arquivo Salvo na Nuvem")
        if c2.button("🗑️", key=f"del_{path_cloud}", help="Excluir arquivo"):
            if storage.delete_file(path_cloud):
                st.toast(f"{label_amigavel} excluído!")
                time.sleep(1)
                st.rerun()
    else:
        # Se não existe, mostra aviso amarelo
        st.warning("⚠️ Pendente de envio")

    # 2. Área de Upload (Sempre visível para permitir sobrescrever)
    arquivo = st.file_uploader(
        f"Enviar {label_amigavel}", 
        type=["xlsx", "csv"], 
        key=f"up_{path_cloud}",
        label_visibility="collapsed"
    )
    
    # 3. Lógica de Envio
    if arquivo:
        with st.spinner("Enviando para o Supabase..."):
            if storage.upload(arquivo, path_cloud):
                st.success("Upload concluído!")
                time.sleep(1)
                st.rerun() # Recarrega para atualizar o status visual acima
            else:
                st.error("Erro ao enviar. Tente novamente.")
    
    st.divider()

# --- COLUNA ALIVVIA ---
with col_alivvia:
    st.header("ALIVVIA")
    st.markdown("---")
    render_file_slot("ALIVVIA", "1. Relatório Full (ML)", "FULL")
    render_file_slot("ALIVVIA", "2. Vendas Externas", "EXT")
    render_file_slot("ALIVVIA", "3. Estoque Físico", "FISICO")

# --- COLUNA JCA ---
with col_jca:
    st.header("JCA")
    st.markdown("---")
    render_file_slot("JCA", "1. Relatório Full (ML)", "FULL")
    render_file_slot("JCA", "2. Vendas Externas", "EXT")
    render_file_slot("JCA", "3. Estoque Físico", "FISICO")