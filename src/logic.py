import pandas as pd
import streamlit as st
import io
from src import storage

def read_file_from_storage(empresa, tipo_arquivo):
    """
    Baixa o arquivo do Supabase, detecta o tipo (XLSX/CSV) e retorna um DataFrame.
    """
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    
    # Baixa o conteúdo (Bytes)
    content = storage.download(path)
    if content is None:
        st.warning(f"Arquivo {tipo_arquivo} da {empresa} não encontrado no Storage.")
        return None

    # Detecta o tipo pelo nome (usamos .xlsx como padrão, mas pode ser CSV)
    is_csv = tipo_arquivo.upper() in ["EXT", "FISICO"] 

    try:
        if is_csv:
            # Arquivo CSV (Vendas Externas/Estoque)
            df = pd.read_csv(
                io.BytesIO(content), 
                encoding='latin1', 
                sep=';', 
                decimal=',',
                on_bad_lines='skip'
            )
        else:
            # Arquivo XLSX (Relatório Full)
            df = pd.read_excel(io.BytesIO(content))
        
        return df

    except Exception as e:
        st.error(f"Erro ao processar o arquivo {tipo_arquivo} da {empresa}. Detalhes: {e}")
        return None

# --- As funções principais do sistema dependem da função acima ---

@st.cache_data(ttl=600)
def get_relatorio_full(empresa):
    """Carrega o relatório FULL (XLSX)"""
    return read_file_from_storage(empresa, "FULL")

@st.cache_data(ttl=600)
def get_vendas_externas(empresa):
    """Carrega Vendas Externas (CSV)"""
    return read_file_from_storage(empresa, "EXT")

@st.cache_data(ttl=600)
def get_estoque_fisico(empresa):
    """Carrega Estoque Físico (CSV)"""
    return read_file_from_storage(empresa, "FISICO")

# --- Função de cálculo de reposição (Simplificada para teste) ---

def calcular_reposicao(empresa):
    df_full = get_relatorio_full(empresa)
    df_ext = get_vendas_externas(empresa)
    df_fisico = get_estoque_fisico(empresa)

    if df_full is None or df_ext is None or df_fisico is None:
        st.warning("Um ou mais arquivos de base estão faltando ou com erro. Reposição não calculada.")
        return None

    # Lógica de Merge e Cálculo (Aqui deve entrar sua lógica complexa de V45/V46)
    
    # Exemplo: Apenas retorna o Full para garantir que a leitura funciona
    return df_full