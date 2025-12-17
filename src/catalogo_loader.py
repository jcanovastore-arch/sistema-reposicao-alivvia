import pandas as pd
import streamlit as st
import io
import requests
from src import utils

def load_from_google_sheets(url):
    try:
        response = requests.get(url)
        content = io.BytesIO(response.content)
        
        # AJUSTADO: Lendo agora da aba CATALOGO_SIMPLES
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normaliza nomes de colunas
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # Limpeza de SKUs
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Planilha Drive (Aba CATALOGO_SIMPLES): {e}")
        return None