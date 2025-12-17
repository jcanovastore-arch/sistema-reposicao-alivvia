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
        
        # Lê as abas específicas
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        # Normalização básica de nomes de colunas
        df_catalogo.columns = [str(c).strip().lower() for c in df_catalogo.columns]
        df_kits.columns = [str(c).strip().lower() for c in df_kits.columns]
        
        # --- FORÇAR MAPEAMENTO DO CATÁLOGO ---
        # Procura por qualquer coluna que contenha 'sku' ou 'codigo'
        sku_col = None
        for c in df_catalogo.columns:
            if 'sku' in c or 'codigo' in c or 'item' in c:
                sku_col = c
                break
        
        if sku_col:
            df_catalogo.rename(columns={sku_col: 'sku'}, inplace=True)
        else:
            # Se não encontrar, força a primeira coluna como 'sku'
            df_catalogo.rename(columns={df_catalogo.columns[0]: 'sku'}, inplace=True)

        # --- MAPEAR KITS (Exatamente como o seu CSV enviado) ---
        df_kits.rename(columns={
            'kit_sku': 'sku_kit',
            'component_sku': 'sku_componente',
            'qty_por_kit': 'quantidade_componente'
        }, inplace=True, errors='ignore')

        # Limpeza de SKUs
        df_catalogo['sku'] = df_catalogo['sku'].astype(str).str.strip().str.upper()
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].astype(str).str.strip().str.upper()
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].astype(str).str.strip().str.upper()
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Drive: {e}")
        return None