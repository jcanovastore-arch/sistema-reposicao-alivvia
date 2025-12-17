import streamlit as st
from supabase import create_client
import io

def get_client():
    """Tenta criar o cliente Supabase com as secrets."""
    try:
        return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])
    except Exception as e:
        # Mantém este erro para diagnóstico de credenciais
        st.error(f"Erro Configuração Secrets: {e}")
        return None

BUCKET = "arquivos"

def upload(file_obj, path):
    """Envia arquivo e retorna True/False. Corrige o MIME Type do CSV."""
    c = get_client()
    if not c: return False
    try:
        content = file_obj.getvalue()
        
        # --- CORREÇÃO DO TIPO MIME PARA CSV ---
        # Garante que o Supabase receba o tipo correto, evitando o erro 'text/csv files are not allowed'
        if file_obj.type in ['text/csv', 'application/csv']:
            mime_type = 'text/csv'
        else:
            mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        # -------------------------------------
        
        # Tenta remover anterior para evitar conflito de cache
        try: c.storage.from_(BUCKET).remove([path])
        except: pass
        
        # Upload
        c.storage.from_(BUCKET).upload(path, content, {"content-type": mime_type, "upsert": "true"})
        return True
    except Exception as e:
        st.error(f"ERRO SUPABASE: {e}") 
        return False

def delete_file(path):
    """Apaga arquivo da nuvem"""
    c = get_client()
    if not c: return False
    try:
        c.storage.from_(BUCKET).remove([path])
        return True
    except Exception as e:
        st.error(f"Erro ao deletar: {e}")
        return False

def file_exists(path):
    """Checa se arquivo existe (rápido)"""
    c = get_client()
    if not c: return False
    try:
        folder = "/".join(path.split("/")[:-1])
        filename = path.split("/")[-1]
        res = c.storage.from_(BUCKET).list(folder, {"search": filename})
        return len(res) > 0
    except:
        return False

def download(path):
    """Baixa o conteúdo"""
    c = get_client()
    if not c: return None
    try:
        return c.storage.from_(BUCKET).download(path)
    except:
        return None