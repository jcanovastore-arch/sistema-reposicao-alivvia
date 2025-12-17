import pandas as pd
import streamlit as st
import io
import requests
from src import utils

URL_PADRAO = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def load_catalogo_padrao(url=URL_PADRAO):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        content = io.BytesIO(response.content)
        
        # Lê as abas CATALOGO_SIMPLES e KITS
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normalização manual robusta (Tudo minúsculo e sem espaços)
        df_catalogo.columns = [str(c).strip().lower() for c in df_catalogo.columns]
        df_kits.columns = [str(c).strip().lower() for c in df_kits.columns]
        
        # --- IDENTIFICAR SKU NO CATÁLOGO ---
        possiveis_skus = ['sku', 'kit_sku', 'codigo', 'cod', 'item', 'referencia']
        sku_col_found = None
        for col in df_catalogo.columns:
            if any(p == col or p in col for p in possiveis_skus):
                sku_col_found = col
                break
        
        if sku_col_found:
            df_catalogo.rename(columns={sku_col_found: 'sku'}, inplace=True)
        else:
            # Fallback: assume que a primeira coluna é o SKU se não achar nada
            df_catalogo.rename(columns={df_catalogo.columns[0]: 'sku'}, inplace=True)

        # --- MAPEAMENTO DA ABA KITS (Baseado no seu arquivo) ---
        df_kits.rename(columns={
            'kit_sku': 'sku_kit',
            'component_sku': 'sku_componente',
            'qty_por_kit': 'quantidade_componente',
            'quantidade': 'quantidade_componente'
        }, inplace=True, errors='ignore')

        # Limpeza e Padronização de valores (MAIÚSCULO E LIMPO)
        def clean_sku(val):
            return str(val).strip().upper() if pd.notnull(val) else ""

        df_catalogo['sku'] = df_catalogo['sku'].apply(clean_sku)
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(clean_sku)
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].apply(clean_sku)
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Planilha Drive: {e}")
        return None