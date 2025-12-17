import pandas as pd
import streamlit as st
import io
import requests
from unidecode import unidecode

# CONFIGURAÇÃO
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def norm_header_kits(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    # Sinônimos KITS
    if s in ['kit_sku', 'sku_kit', 'kit', 'sku_pai', 'pai', 'produto_pai', 'sku']: return 'sku_kit'
    if s in ['component_sku', 'sku_componente', 'componente', 'filho', 'sku_filho', 'item']: return 'sku_componente'
    if s in ['qty_por_kit', 'quantidade', 'qtd', 'qtde', 'quantidade_no_kit', 'fator']: return 'quantidade_no_kit'
    return s.replace(" ", "_")

def norm_header_catalogo(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    # Sinônimos CATÁLOGO
    if s in ['sku', 'codigo', 'produto', 'id', 'codigo_sku']: return 'sku'
    if s in ['custo', 'custo_medio', 'preco_custo', 'valor_custo', 'preco', 'custo_un']: return 'custo_medio'
    if s in ['fornecedor', 'fabricante', 'marca', 'origem']: return 'fornecedor'
    return s.replace(" ", "_")

@st.cache_data(ttl=0)
def load_catalogo_padrao():
    try:
        response = requests.get(GOOGLE_SHEETS_URL)
        response.raise_for_status()
        excel_data = io.BytesIO(response.content)

        try:
            df_kits = pd.read_excel(excel_data, sheet_name="KITS")
            df_catalogo = pd.read_excel(excel_data, sheet_name="CATALOGO_SIMPLES")
        except ValueError as e:
            st.error(f"Erro nas abas do Excel: {e}")
            return None

        # 1. Tenta traduzir os nomes
        df_kits.columns = [norm_header_kits(c) for c in df_kits.columns]
        df_catalogo.columns = [norm_header_catalogo(c) for c in df_catalogo.columns]

        # --- A BLINDAGEM (O SEGREDO DA PAZ) ---
        # Se a coluna não existir, CRIA ELA NA MARRA. Sem choro, sem erro.
        
        # Blindagem KITS
        if 'sku_kit' not in df_kits.columns: df_kits['sku_kit'] = "DESCONHECIDO"
        if 'sku_componente' not in df_kits.columns: df_kits['sku_componente'] = "DESCONHECIDO"
        if 'quantidade_no_kit' not in df_kits.columns: df_kits['quantidade_no_kit'] = 1

        # Blindagem CATÁLOGO (Aqui estava o seu erro)
        if 'sku' not in df_catalogo.columns: 
             # Se não tem SKU no catálogo, tenta pegar a primeira coluna
             if len(df_catalogo.columns) > 0:
                 df_catalogo.rename(columns={df_catalogo.columns[0]: 'sku'}, inplace=True)
             else:
                 df_catalogo['sku'] = "DESCONHECIDO"

        if 'custo_medio' not in df_catalogo.columns: 
            df_catalogo['custo_medio'] = 0.0 # Cria com valor zero
            
        if 'fornecedor' not in df_catalogo.columns: 
            df_catalogo['fornecedor'] = "GERAL" # Cria com valor genérico

        # Conversão de Tipos para evitar erro de merge
        df_kits['sku_kit'] = df_kits['sku_kit'].astype(str)
        df_kits['sku_componente'] = df_kits['sku_componente'].astype(str)
        df_catalogo['sku'] = df_catalogo['sku'].astype(str)

        st.session_state['catalogo_carregado'] = True
        return {"kits": df_kits, "catalogo": df_catalogo}

    except Exception as e:
        st.error(f"Erro no download: {e}")
        return None