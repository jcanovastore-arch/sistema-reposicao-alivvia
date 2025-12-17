import pandas as pd
import streamlit as st
import io
import requests
from src import utils

# LINK DIRETO DA SUA PLANILHA (Aba CATALOGO_SIMPLES e KITS)
URL_PADRAO = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def load_catalogo_padrao(url=URL_PADRAO):
    """
    Carrega o catálogo. Se não receber uma URL, usa a URL_PADRAO automaticamente.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        content = io.BytesIO(response.content)
        
        # Lê as abas específicas que você definiu
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normaliza as colunas (congelado)
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # Padroniza SKUs para maiúsculo
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Planilha: {e}")
        return None