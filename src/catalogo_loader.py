import pandas as pd
import streamlit as st
import io
import requests
from unidecode import unidecode

# --- URL DO SEU CATÁLOGO PADRÃO ---
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

def norm_header_kits(s: str) -> str:
    # Limpa o nome da coluna (remove acentos, espaços extras, deixa minusculo)
    s = unidecode(str(s).lower().strip())
    
    # --- TRADUTOR DA ABA KITS ---
    # Se encontrar qualquer um destes nomes, entende como 'sku_kit'
    if s in ['sku_kit', 'kit', 'sku_pai', 'pai', 'produto_pai', 'sku', 'codigo_pai']: return 'sku_kit'
    
    # Se encontrar estes, entende como 'sku_componente'
    if s in ['sku_componente', 'componente', 'filho', 'sku_filho', 'produto_filho', 'item']: return 'sku_componente'
    
    # Se encontrar estes, entende como 'quantidade_no_kit'
    if s in ['quantidade', 'qtd', 'qtde', 'quantidade_no_kit', 'fator', 'unidades']: return 'quantidade_no_kit'
    
    return s.replace(" ", "_")

def norm_header_catalogo(s: str) -> str:
    s = unidecode(str(s).lower().strip())
    
    # --- TRADUTOR DA ABA CATALOGO_SIMPLES ---
    if s in ['sku', 'codigo', 'produto', 'id', 'codigo_sku']: return 'sku'
    if s in ['custo', 'custo_medio', 'preco_custo', 'valor_custo', 'preco']: return 'custo_medio'
    if s in ['fornecedor', 'fabricante', 'marca']: return 'fornecedor'
    
    return s.replace(" ", "_")

@st.cache_data(ttl=3600, show_spinner="Baixando e traduzindo Catálogo Padrão...")
def load_catalogo_padrao():
    try:
        # 1. Download
        response = requests.get(GOOGLE_SHEETS_URL)
        response.raise_for_status()
        excel_data = io.BytesIO(response.content)

        # 2. Ler Abas
        try:
            df_kits = pd.read_excel(excel_data, sheet_name="KITS")
            df_catalogo = pd.read_excel(excel_data, sheet_name="CATALOGO_SIMPLES")
        except ValueError as e:
            st.error(f"Erro nas Abas: Verifique se sua planilha tem as abas 'KITS' e 'CATALOGO_SIMPLES'. Detalhe: {e}")
            return None

        # 3. Aplicar a Tradução Inteligente
        df_kits.columns = [norm_header_kits(c) for c in df_kits.columns]
        df_catalogo.columns = [norm_header_catalogo(c) for c in df_catalogo.columns]

        # 4. Validação de Segurança (Mostra erro claro se falhar)
        missing_kits = [col for col in ['sku_kit', 'sku_componente', 'quantidade_no_kit'] if col not in df_kits.columns]
        if missing_kits:
            st.error(f"❌ Erro na aba KITS: Não encontrei as colunas: {missing_kits}. Colunas lidas: {list(df_kits.columns)}")
            return None
            
        if 'sku' not in df_catalogo.columns:
            st.error(f"❌ Erro na aba CATALOGO: Não encontrei a coluna 'SKU'. Colunas lidas: {list(df_catalogo.columns)}")
            return None

        st.session_state['catalogo_carregado'] = True
        # st.success("Catálogo atualizado e traduzido com sucesso!") # Comentei para não poluir a tela
        return {
            "kits": df_kits,
            "catalogo": df_catalogo
        }

    except Exception as e:
        st.error(f"Erro crítico ao baixar catálogo: {e}")
        return None