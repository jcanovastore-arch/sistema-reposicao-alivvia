import pandas as pd
import streamlit as st
import io
import requests
from src import utils

# Verifique se este link abre no seu navegador. Se não abrir, o erro é no link.
URL_PADRAO = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def load_catalogo_padrao(url=URL_PADRAO):
    try:
        # 1. Tenta baixar o arquivo
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        content = io.BytesIO(response.content)
        
        # 2. Tenta ler as abas (aqui é onde geralmente trava se o nome mudar)
        # Usei um try/except específico para as abas
        try:
            df_catalogo = pd.read_excel(content, sheet_name="CATALOGO_SIMPLES")
            # Reseta o ponteiro para ler a outra aba do mesmo arquivo
            content.seek(0)
            df_kits = pd.read_excel(content, sheet_name="KITS")
        except Exception as e_aba:
            st.error(f"❌ Erro nas abas: Verifique se os nomes 'CATALOGO_SIMPLES' e 'KITS' estão corretos no Drive. Erro: {e_aba}")
            return None
        
        # 3. Normalização (Sua lógica congelada)
        df_catalogo = utils.normalize_cols(df_catalogo)
        df_kits = utils.normalize_cols(df_kits)
        
        if 'sku' in df_catalogo.columns:
            df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
        
        if 'sku_kit' in df_kits.columns:
            df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
            
        return {"catalogo": df_catalogo, "kits": df_kits}

    except requests.exceptions.RequestException as e_net:
        st.error(f"🌐 Erro de conexão com o Google Sheets: {e_net}")
        return None
    except Exception as e:
        st.error(f"🚨 Erro inesperado: {e}")
        return None