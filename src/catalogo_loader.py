import pandas as pd
import streamlit as st
import io
import requests
from unidecode import unidecode
from src import utils

def load_from_google_sheets(url):
    try:
        response = requests.get(url)
        content = io.BytesIO(response.content)
        # Lê as duas abas do Sheets
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO")
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normaliza Colunas
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # Garante SKUs limpos e em maiúsculo
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)

        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Google Sheets: {e}")
        return None