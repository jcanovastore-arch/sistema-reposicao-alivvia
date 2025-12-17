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
        
        # Lê as abas específicas do seu Drive
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normalização agressiva (remove espaços e põe tudo em minúsculo)
        df_catalogo.columns = [str(c).strip().lower() for c in df_catalogo.columns]
        df_kits.columns = [str(c).strip().lower() for c in df_kits.columns]
        
        # --- BUSCA O SKU NO CATÁLOGO ---
        sku_col = next((c for c in df_catalogo.columns if any(k in c for k in ['sku', 'codigo', 'item'])), df_catalogo.columns[0])
        df_catalogo.rename(columns={sku_col: 'sku'}, inplace=True)

        # --- MAPEIA OS KITS (Conforme a sua planilha enviada) ---
        df_kits.rename(columns={
            'kit_sku': 'sku_kit',
            'component_sku': 'sku_componente',
            'qty_por_kit': 'quantidade_componente'
        }, inplace=True)

        # Limpeza de SKUs para o Merge não falhar
        df_catalogo['sku'] = df_catalogo['sku'].astype(str).str.strip().str.upper()
        df_kits['sku_kit'] = df_kits['sku_kit'].astype(str).str.strip().str.upper()
        df_kits['sku_componente'] = df_kits['sku_componente'].astype(str).str.strip().str.upper()
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro na Planilha: {e}")
        return None