import pandas as pd
import streamlit as st
import io
import requests
from unidecode import unidecode

# CONFIGURAÇÃO
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def norm_header_kits(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    
    # --- MAPEAMENTO EXATO PARA SUAS COLUNAS ---
    # Aqui adicionei os nomes que apareceram no seu erro:
    if s in ['kit_sku', 'sku_kit', 'kit', 'sku_pai']: return 'sku_kit'
    if s in ['component_sku', 'sku_componente', 'componente', 'sku_filho']: return 'sku_componente'
    if s in ['qty_por_kit', 'quantidade', 'qtd', 'qtde', 'quantidade_no_kit']: return 'quantidade_no_kit'
    
    return s.replace(" ", "_")

def norm_header_catalogo(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    
    if s in ['sku', 'codigo', 'produto', 'id', 'codigo_sku']: return 'sku'
    if s in ['custo', 'custo_medio', 'preco_custo', 'valor_custo', 'preco', 'custo_un']: return 'custo_medio'
    if s in ['fornecedor', 'fabricante', 'marca']: return 'fornecedor'
    
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

        # 1. Aplica a tradução com os novos nomes
        df_kits.columns = [norm_header_kits(c) for c in df_kits.columns]
        df_catalogo.columns = [norm_header_catalogo(c) for c in df_catalogo.columns]

        # 2. Validação Final
        required_kits = ['sku_kit', 'sku_componente', 'quantidade_no_kit']
        missing = [c for c in required_kits if c not in df_kits.columns]
        
        if missing:
            # Se ainda falhar, tentamos pela posição (Último recurso)
            if len(df_kits.columns) >= 3:
                # st.warning("Renomeando colunas pela posição...")
                cols = list(df_kits.columns)
                df_kits.rename(columns={cols[0]: 'sku_kit', cols[1]: 'sku_componente', cols[2]: 'quantidade_no_kit'}, inplace=True)
            else:
                st.error(f"❌ ERRO NA ABA KITS. Colunas esperadas: {required_kits}. Colunas encontradas: {list(df_kits.columns)}")
                return None
            
        st.session_state['catalogo_carregado'] = True
        return {"kits": df_kits, "catalogo": df_catalogo}

    except Exception as e:
        st.error(f"Erro no download: {e}")
        return None