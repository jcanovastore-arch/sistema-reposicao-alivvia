import streamlit as st
from . import logic 

def carregar_bases_para_calculo(empresa):
    """
    Carrega os DataFrames do Supabase e do Google Sheets.
    """
    # 1. Busca no Supabase (via logic.py)
    df_full = logic.get_relatorio_full(empresa)
    df_ext = logic.get_vendas_externas(empresa)
    df_fisico = logic.get_estoque_fisico(empresa)

    # 2. Busca o Catálogo que foi carregado na Home
    dados_catalogo = st.session_state.get('catalogo_dados')
    
    # 3. Verificação de integridade
    if df_full is None or df_fisico is None or dados_catalogo is None:
        return None
        
    return {
        "df_full": df_full,
        "df_ext": df_ext,
        "df_fisico": df_fisico,
        "catalogo_kits": dados_catalogo['kits'],
        "catalogo_simples": dados_catalogo['catalogo']
    }