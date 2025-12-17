import pandas as pd
import streamlit as st
import io
import requests

# --- URL DO SEU CATÁLOGO PADRÃO (Link de exportação XLSX) ---
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

@st.cache_data(ttl=3600, show_spinner="Baixando e processando Catálogo Padrão...")
def load_catalogo_padrao():
    """Baixa, lê e normaliza as abas KITS e CATALOGO_SIMPLES."""
    try:
        # 1. Faz o download do arquivo XLSX
        response = requests.get(GOOGLE_SHEETS_URL)
        response.raise_for_status()

        # 2. Converte o conteúdo binário para um buffer
        excel_data = io.BytesIO(response.content)

        # 3. Lê as duas abas necessárias
        df_kits = pd.read_excel(excel_data, sheet_name="KITS")
        df_catalogo = pd.read_excel(excel_data, sheet_name="CATALOGO_SIMPLES")

        # 4. Normalização das colunas
        df_kits.columns = [col.lower().strip().replace(' ', '_') for col in df_kits.columns]
        df_catalogo.columns = [col.lower().strip().replace(' ', '_') for col in df_catalogo.columns]

        if df_kits.empty or df_catalogo.empty:
             st.warning("Catálogo Padrão carregado, mas uma das abas (KITS ou CATALOGO_SIMPLES) está vazia.")
             return None
             
        st.session_state['catalogo_carregado'] = True
        st.success("Catálogo Padrão (KITS/CATALOGO) carregado com sucesso!")
        return {
            "kits": df_kits,
            "catalogo": df_catalogo
        }

    except requests.exceptions.HTTPError as e:
        st.error(f"Erro ao baixar Catálogo: Verifique o link e se a planilha está pública. (Erro: {e})")
        return None
    except Exception as e:
        st.error(f"Erro ao processar a planilha. Detalhes: {e}")
        return None