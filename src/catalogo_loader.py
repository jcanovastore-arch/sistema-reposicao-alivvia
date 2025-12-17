import pandas as pd
import streamlit as st
import io
import requests
from src import utils

def load_catalogo_padrao(url):
    """
    Lê o catálogo do Google Sheets (aba CATALOGO_SIMPLES)
    e os kits (aba KITS).
    """
    try:
        response = requests.get(url)
        # Verifica se o link do Google Sheets está acessível
        response.raise_for_status() 
        
        content = io.BytesIO(response.content)
        
        # Lê as abas específicas
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normaliza as colunas (converte para minúsculo, tira espaços e acentos)
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # Padronização de SKUs para garantir que o sistema "enxergue" os produtos
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
        
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Planilha Drive: {e}")
        return None