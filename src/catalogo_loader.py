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
        
        # Lê as abas CATALOGO_SIMPLES e KITS
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # --- BUSCA AUTOMÁTICA DE COLUNAS NO CATÁLOGO ---
        for col in df_catalogo.columns:
            if col in ['sku', 'codigo', 'cod', 'item', 'codigo_sku']:
                df_catalogo.rename(columns={col: 'sku'}, inplace=True)
                break
        
        # --- BUSCA AUTOMÁTICA DE COLUNAS NOS KITS (Resolve o KeyError) ---
        for col in df_kits.columns:
            # Procura coluna do Kit
            if col in ['sku_kit', 'kit', 'sku_pai', 'pai']:
                df_kits.rename(columns={col: 'sku_kit'}, inplace=True)
            # Procura coluna do Componente
            if col in ['sku_componente', 'componente', 'item_filho', 'filho', 'sku_item']:
                df_kits.rename(columns={col: 'sku_componente'}, inplace=True)
            # Procura coluna da Quantidade
            if col in ['quantidade_componente', 'quantidade', 'qtde', 'qtd']:
                df_kits.rename(columns={col: 'quantidade_componente'}, inplace=True)

        # Padroniza SKUs
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Drive: {e}")
        return None