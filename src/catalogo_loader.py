import pandas as pd
import streamlit as st
import io
import requests
from src import utils

URL_PADRAO = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def load_catalogo_padrao(url=URL_PADRAO):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        content = io.BytesIO(response.content)
        
        # Lê a aba que você determinou
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normaliza os nomes das colunas (tira espaços, acentos, etc)
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # --- SOLUÇÃO DO KEYERROR ---
        # Procura por variações de nome e força para 'sku'
        possiveis_skus = ['sku', 'codigo', 'cod', 'item', 'produto', 'codigo_sku']
        for col in df_catalogo.columns:
            if col in possiveis_skus:
                df_catalogo.rename(columns={col: 'sku'}, inplace=True)
                break
        
        # Se mesmo assim não achar a coluna 'sku', pega a PRIMEIRA coluna da planilha
        if 'sku' not in df_catalogo.columns:
            df_catalogo.rename(columns={df_catalogo.columns[0]: 'sku'}, inplace=True)

        # Limpa os valores do SKU
        df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        
        return {"catalogo": df_catalogo, "kits": df_kits}

    except Exception as e:
        st.error(f"Erro ao carregar Planilha: {e}")
        return None