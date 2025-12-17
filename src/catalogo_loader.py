import pandas as pd
import streamlit as st
import io
import requests
from unidecode import unidecode

# --- CONFIGURAÇÃO ---
# Se mudar o link da planilha no futuro, altere aqui
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def norm_header_kits(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    
    # TRADUTOR DA ABA KITS
    if s in ['sku_kit', 'kit', 'sku_pai', 'pai', 'produto_pai', 'sku']: return 'sku_kit'
    if s in ['sku_componente', 'componente', 'filho', 'sku_filho', 'item']: return 'sku_componente'
    if s in ['quantidade', 'qtd', 'qtde', 'quantidade_no_kit', 'fator']: return 'quantidade_no_kit'
    
    return s.replace(" ", "_")

def norm_header_catalogo(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    
    # TRADUTOR DA ABA CATALOGO
    if s in ['sku', 'codigo', 'produto', 'id']: return 'sku'
    if s in ['custo', 'custo_medio', 'preco_custo', 'valor_custo']: return 'custo_medio'
    if s in ['fornecedor', 'fabricante', 'marca']: return 'fornecedor'
    
    return s.replace(" ", "_")

@st.cache_data(ttl=3600, show_spinner="Baixando Catálogo Padrão...")
def load_catalogo_padrao():
    try:
        # 1. Download
        response = requests.get(GOOGLE_SHEETS_URL)
        response.raise_for_status()
        excel_data = io.BytesIO(response.content)

        # 2. Ler Abas
        # Lê aba KITS
        df_kits = pd.read_excel(excel_data, sheet_name="KITS")
        # Lê aba CATALOGO
        df_catalogo = pd.read_excel(excel_data, sheet_name="CATALOGO_SIMPLES")

        # 3. Aplicar Tradução de Colunas (O SEGREDO DA CORREÇÃO)
        df_kits.columns = [norm_header_kits(c) for c in df_kits.columns]
        df_catalogo.columns = [norm_header_catalogo(c) for c in df_catalogo.columns]

        # 4. Validação de Segurança
        if 'sku_kit' not in df_kits.columns:
            st.error(f"Erro na aba KITS: Não achei a coluna 'SKU Kit'. Colunas lidas: {list(df_kits.columns)}")
            return None
            
        if 'sku' not in df_catalogo.columns:
            st.error(f"Erro na aba CATALOGO: Não achei a coluna 'SKU'. Colunas lidas: {list(df_catalogo.columns)}")
            return None

        st.session_state['catalogo_carregado'] = True
        return {
            "kits": df_kits,
            "catalogo": df_catalogo
        }

    except Exception as e:
        st.error(f"Erro ao baixar catálogo do Google Sheets: {e}")
        return None