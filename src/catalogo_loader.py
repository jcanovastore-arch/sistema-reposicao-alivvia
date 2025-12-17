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
        
        # Lê as abas
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normalização de nomes de colunas
        df_catalogo.columns = [str(c).strip().lower() for c in df_catalogo.columns]
        df_kits.columns = [str(c).strip().lower() for c in df_kits.columns]
        
        # --- CAÇA SKU NO CATÁLOGO ---
        sku_col = None
        for c in df_catalogo.columns:
            if any(k in c for k in ['sku', 'codigo', 'item', 'referencia']):
                sku_col = c
                break
        if sku_col:
            df_catalogo.rename(columns={sku_col: 'sku'}, inplace=True)
        else:
            df_catalogo.rename(columns={df_catalogo.columns[0]: 'sku'}, inplace=True)

        # --- CAÇA COLUNAS NOS KITS (Baseado no seu arquivo enviado) ---
        for c in df_kits.columns:
            if 'kit_sku' in c or 'kit' in c: df_kits.rename(columns={c: 'sku_kit'}, inplace=True)
            elif 'component' in c or 'item' in c: df_kits.rename(columns={c: 'sku_componente'}, inplace=True)
            elif 'qty' in c or 'qtd' in c or 'quant' in c: df_kits.rename(columns={c: 'quantidade_componente'}, inplace=True)

        # Limpeza final dos SKUs
        df_catalogo['sku'] = df_catalogo['sku'].astype(str).str.strip().str.upper()
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].astype(str).str.strip().str.upper()
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].astype(str).str.strip().str.upper()
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro no Catálogo: {e}")
        return None