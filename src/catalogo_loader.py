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
        
        # Lê as abas CATALOGO_SIMPLES e KITS
        df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
        content.seek(0)
        df_kits = pd.read_excel(content, sheet_name="KITS")
        
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        # --- MAPEAR COLUNAS DO CATÁLOGO (Aba CATALOGO_SIMPLES) ---
        achou_sku = False
        for col in df_catalogo.columns:
            if col in ['sku', 'kit_sku', 'codigo', 'cod', 'item', 'referencia']:
                df_catalogo.rename(columns={col: 'sku'}, inplace=True)
                achou_sku = True
                break
        if not achou_sku:
            df_catalogo.rename(columns={df_catalogo.columns[0]: 'sku'}, inplace=True)

        # --- MAPEAR COLUNAS DOS KITS (Baseado no seu ficheiro) ---
        # kit_sku -> sku_kit | component_sku -> sku_componente | qty_por_kit -> quantidade_componente
        df_kits.rename(columns={
            'kit_sku': 'sku_kit',
            'component_sku': 'sku_componente',
            'qty_por_kit': 'quantidade_componente'
        }, inplace=True)

        # Limpeza e Padronização
        df_catalogo['sku'] = df_catalogo['sku'].astype(str).apply(utils.norm_sku)
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].astype(str).apply(utils.norm_sku)
        if 'sku_componente' in df_kits.columns:
            df_kits['sku_componente'] = df_kits['sku_componente'].astype(str).apply(utils.norm_sku)
            
        return {"catalogo": df_catalogo, "kits": df_kits}
    except Exception as e:
        st.error(f"Erro ao carregar Drive: {e}")
        return None