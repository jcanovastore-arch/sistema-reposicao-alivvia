import streamlit as st
# Importa APENAS funções existentes no logic.py
from .logic import get_relatorio_full, get_vendas_externas, get_estoque_fisico 

# --- FUNÇÃO PARA PEGAR TODOS OS ARQUIVOS BASE ---
def carregar_bases_para_calculo(empresa):
    """
    Carrega todos os DataFrames necessários para o cálculo de reposição.
    """
    # 1. Dados carregados via Upload (Supabase)
    df_full = get_relatorio_full(empresa)
    df_ext = get_vendas_externas(empresa) # Não usado na lógica de compra, mas bom ter
    df_fisico = get_estoque_fisico(empresa)

    # 2. Dados carregados via Google Sheets (Catálogo Padrão)
    dados_catalogo = st.session_state.get('catalogo_dados')
    
    # 3. Verificação
    bases_ok = (
        df_full is not None and 
        df_fisico is not None and
        dados_catalogo is not None
    )

    if not bases_ok:
        # Se as bases falharam, a função de cálculo não será chamada.
        return None
        
    return {
        "df_full": df_full,
        "df_ext": df_ext,
        "df_fisico": df_fisico,
        "catalogo_kits": dados_catalogo['kits'],
        "catalogo_simples": dados_catalogo['catalogo']
    }