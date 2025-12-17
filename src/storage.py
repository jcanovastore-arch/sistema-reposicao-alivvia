import streamlit as st
from supabase import create_client

def get_client():
    try:
        return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])
    except:
        return None

BUCKET = "arquivos"

def upload(file_obj, path):
    """Envia arquivo e retorna True/False"""
    c = get_client()
    if not c: return False
    try:
        content = file_obj.getvalue()
        # Tenta remover anterior para evitar conflito de cache
        try: c.storage.from_(BUCKET).remove([path])
        except: pass
        
        c.storage.from_(BUCKET).upload(path, content, {"content-type": file_obj.type, "upsert": "true"})
        return True
    except Exception as e:
        return False

def delete_file(path):
    """Apaga arquivo da nuvem"""
    c = get_client()
    if not c: return False
    try:
        c.storage.from_(BUCKET).remove([path])
        return True
    except:
        return False

def file_exists(path):
    """Checa se arquivo existe (rápido)"""
    c = get_client()
    if not c: return False
    try:
        # Tenta listar o arquivo na pasta
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