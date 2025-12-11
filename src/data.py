import pandas as pd
import streamlit as st
from pathlib import Path
import io

def get_local_file_path(filename):
    """Retorna o caminho absoluto para um arquivo na pasta data/"""
    return Path(__file__).parent.parent / 'data' / filename

def get_local_name_path(filename):
    """Retorna apenas o nome do arquivo (atalho simples)"""
    return filename

def load_any_table_from_bytes(file_bytes, filename):
    """
    Carrega DataFrame a partir de bytes (upload), detectando csv ou excel.
    """
    try:
        if filename.endswith('.csv'):
            return pd.read_csv(file_bytes)
        else:
            return pd.read_excel(file_bytes)
    except Exception as e:
        st.error(f"Erro ao ler arquivo {filename}: {e}")
        return pd.DataFrame()

def carregar_padrao_local_ou_sheets(uploaded_file, local_path, sheet_id=None, sheet_name=None):
    """
    Tenta carregar, nesta ordem:
    1. Arquivo de Upload (se existir)
    2. Arquivo Local (se existir)
    3. Google Sheets (se sheet_id for fornecido - fallback)
    """
    df = pd.DataFrame()
    origem = "Nenhuma"

    # 1. Prioridade: Upload do Usuário
    if uploaded_file is not None:
        try:
            df = load_any_table_from_bytes(uploaded_file, uploaded_file.name)
            origem = "Upload Manual"
            return df, origem
        except Exception as e:
            st.warning(f"Falha ao ler upload: {e}")

    # 2. Prioridade: Arquivo Local
    path_obj = Path(local_path)
    if path_obj.exists():
        try:
            if str(local_path).endswith('.csv'):
                df = pd.read_csv(local_path)
            else:
                df = pd.read_excel(local_path)
            origem = f"Arquivo Local ({path_obj.name})"
            return df, origem
        except Exception as e:
            st.warning(f"Arquivo local existe mas falhou ao ler: {e}")

    # 3. Prioridade: Google Sheets (se configurado)
    if sheet_id:
        try:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
            if sheet_name:
                url += f"&gid={sheet_name}" # Nota: gid geralmente é numérico, mas aqui simplificamos
            
            df = pd.read_csv(url)
            origem = "Google Sheets (Online)"
            return df, origem
        except Exception as e:
            st.error(f"Não foi possível carregar do Google Sheets: {e}")

    return df, origem