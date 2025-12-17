import pandas as pd
import streamlit as st
import io
import requests
from src import utils

URL_PADRAO = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def load_catalogo_padrao(url=URL_PADRAO):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        content = io.BytesIO(response.content)
        
        # Lê as abas conforme sua planilha
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # --- MAPEAR COLUNAS DO CATÁLOGO ---
        for col in df_catalogo.columns:
            if col in ['sku', 'kit_sku', 'codigo', 'cod', 'item']:
                df_catalogo.rename(columns={col: 'sku'}, inplace=True)
                break
        
        # --- MAPEAR COLUNAS DOS KITS (Baseado no seu arquivo enviado) ---
        mapeamento_kits = {
            'kit_sku': 'sku_kit',
            'component_sku': 'sku_componente',
            'qty_por_kit': 'quantidade_componente'
        }
        df_kits.rename(columns=mapeamento_kits, inplace=True)

        # Padronização de SKUs (Maiúsculo e limpo)
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao acessar Drive: {e}")
        return None