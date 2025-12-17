import streamlit as st
from supabase import create_client

def get_client():
    try:
        return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])
    except:
        return None

BUCKET = "arquivos"

def upload(file_obj, path):
    """Envia para nuvem"""
    c = get_client()
    if not c: return False
    try:
        content = file_obj.getvalue()
        try: c.storage.from_(BUCKET).remove([path])
        except: pass
        c.storage.from_(BUCKET).upload(path, content, {"content-type": file_obj.type, "upsert": "true"})
        return True
    except Exception as e:
        print(e)
        return False

def download(path):
    """Baixa da nuvem"""
    c = get_client()
    if not c: return None
    try:
        return c.storage.from_(BUCKET).download(path)
    except:
        return None