import streamlit as st
import time
from src import storage

st.set_page_config(page_title="Uploads", layout="wide")
st.title("☁️ Gerenciador de Arquivos")

# --- CORREÇÃO DO LOOP: Inicializa um contador na session_state ---
# O contador será usado para forçar a limpeza do widget de upload após o sucesso.
if 'upload_counter' not in st.session_state:
    st.session_state['upload_counter'] = 0

col_alivvia, col_jca = st.columns(2)

def render_file_slot(empresa, label_amigavel, tipo_arquivo):
    """
    Cria um bloco visual para gerenciar um único arquivo.
    """
    path_cloud = f"{empresa}/{tipo_arquivo}.xlsx"
    
    st.markdown(f"**{label_amigavel}**")
    
    # 1. Verifica se já existe na nuvem
    existe = storage.file_exists(path_cloud)
    
    if existe:
        c1, c2 = st.columns([0.8, 0.2])
        c1.success("✅ Arquivo Salvo na Nuvem")
        
        # Lógica para DELETAR
        if c2.button("🗑️", key=f"del_{path_cloud}", help="Excluir arquivo"):
            if storage.delete_file(path_cloud):
                st.toast(f"{label_amigavel} excluído!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Erro ao deletar o arquivo.")
    else:
        st.warning("⚠️ Pendente de envio")

    # 2. Área de Upload 
    # Usamos o contador na key para que o widget seja 'novo' e vazio após o rerun
    arquivo = st.file_uploader(
        f"Enviar {label_amigavel}", 
        type=["xlsx", "csv"], 
        # --- AQUI ESTÁ A CORREÇÃO DO LOOP ---
        key=f"up_{path_cloud}_{st.session_state['upload_counter']}",
        label_visibility="collapsed"
    )
    
    # 3. Lógica de Envio 
    if arquivo:
        with st.spinner("Enviando para o Supabase..."):
            if storage.upload(arquivo, path_cloud):
                st.success("Upload concluído!")
                
                # --- MUDANÇA FINAL CONTRA O LOOP: Incrementa o contador ---
                # Isso muda a chave do uploader e o limpa no próximo rerun.
                st.session_state['upload_counter'] += 1 
                time.sleep(1)
                st.rerun() 
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