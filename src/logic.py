import pandas as pd
import streamlit as st
import io
# Removido: import requests (pois a função de catálogo saiu daqui)
from src import storage

# --- FUNÇÕES DE LEITURA DO SUPABASE (MANTIDAS) ---

def read_file_from_storage(empresa, tipo_arquivo):
    # ... (O restante da função de leitura do Supabase que lida com CSV/XLSX)
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if content is None:
        st.warning(f"Arquivo {tipo_arquivo} da {empresa} não encontrado ou vazio no Storage.")
        return None

    is_csv_slot = tipo_arquivo.upper() in ["EXT", "FISICO"] 
    content_io = io.BytesIO(content)

    if not is_csv_slot:
        try:
            return pd.read_excel(content_io)
        except Exception:
            return None

    # --- Lógica de Leitura CSV ---
    try:
        content_io.seek(0) 
        df = pd.read_csv(content_io, encoding='latin1', sep=';', decimal=',', on_bad_lines='skip')
        if df.shape[1] > 1: return df
    except:
        pass
    try:
        content_io.seek(0)
        df = pd.read_csv(content_io, encoding='latin1', sep=',', decimal='.', on_bad_lines='skip')
        if df.shape[1] > 1: return df
    except:
        pass
    st.error(f"Erro Crítico: Falha ao ler arquivo {tipo_arquivo} (CSV).")
    return None

# --- FUNÇÕES WRAPPER DE ACESSO AOS DADOS ---

@st.cache_data(ttl=600)
def get_relatorio_full(empresa):
    return read_file_from_storage(empresa, "FULL")

@st.cache_data(ttl=600)
def get_vendas_externas(empresa):
    return read_file_from_storage(empresa, "EXT")

@st.cache_data(ttl=600)
def get_estoque_fisico(empresa):
    return read_file_from_storage(empresa, "FISICO")

# --- FUNÇÃO PRINCIPAL DE CÁLCULO ---

def calcular_reposicao(empresa):
    """
    Função que será chamada pelo pages/2_📊_Analise_Compra.py
    """
    df_full = get_relatorio_full(empresa)
    df_ext = get_vendas_externas(empresa)
    df_fisico = get_estoque_fisico(empresa)
    
    # Pega o catálogo da memória (se o Home.py já o tiver carregado)
    dados_catalogo = st.session_state.get('catalogo_dados') 

    if df_full is None or df_ext is None or df_fisico is None or dados_catalogo is None:
        # Não exibe erro aqui, pois a página 2 já faz a verificação.
        return None

    st.success("Arquivos base e Catálogo carregados com sucesso. Processando dados...")
    
    # [AQUI VAI A SUA LÓGICA DE MERGE E CÁLCULO]
    
    return df_full