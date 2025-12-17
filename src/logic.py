import pandas as pd
import streamlit as st
import io
import requests # Necessário para baixar do Google Sheets
from src import storage

# --- URL DO SEU CATÁLOGO PADRÃO (Para download XLSX direto) ---
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1cTLARjq-B5g50dL6tcntg7lb_Iu0ta43/export?format=xlsx"

@st.cache_data(ttl=3600, show_spinner="Baixando e processando Catálogo Padrão...")
def load_catalogo_padrao():
    """Baixa, lê e normaliza as abas KITS e CATALOGO_SIMPLES do Google Sheets."""
    try:
        # 1. Faz o download
        response = requests.get(GOOGLE_SHEETS_URL)
        response.raise_for_status() # Verifica se o status é 200 (OK)

        # 2. Converte para buffer
        excel_data = io.BytesIO(response.content)

        # 3. Lê as duas abas
        df_kits = pd.read_excel(excel_data, sheet_name="KITS")
        df_catalogo = pd.read_excel(excel_data, sheet_name="CATALOGO_SIMPLES")

        # 4. Normalização das colunas
        df_kits.columns = [col.lower().strip().replace(' ', '_') for col in df_kits.columns]
        df_catalogo.columns = [col.lower().strip().replace(' ', '_') for col in df_catalogo.columns]

        if df_kits.empty or df_catalogo.empty:
             st.warning("Catálogo Padrão carregado, mas uma das abas (KITS ou CATALOGO_SIMPLES) está vazia.")
             return None
             
        # Sinaliza que o catálogo foi carregado
        st.session_state['catalogo_carregado'] = True
        st.success("Catálogo Padrão (KITS/CATALOGO) carregado com sucesso!")
        return {
            "kits": df_kits,
            "catalogo": df_catalogo
        }

    except requests.exceptions.HTTPError as e:
        st.error(f"Erro ao baixar: Verifique o link e se a planilha está pública. (Erro: {e})")
        return None
    except Exception as e:
        st.error(f"Erro ao processar a planilha. Detalhes: {e}")
        return None


def read_file_from_storage(empresa, tipo_arquivo):
    """
    Baixa o arquivo do Supabase, detecta o tipo (XLSX/CSV) e retorna um DataFrame.
    """
    # O path no Supabase foi padronizado para .xlsx (para simplificar o storage)
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    
    content = storage.download(path)
    if content is None:
        st.warning(f"Arquivo {tipo_arquivo} da {empresa} não encontrado ou vazio no Storage.")
        return None

    is_csv_slot = tipo_arquivo.upper() in ["EXT", "FISICO"] 
    content_io = io.BytesIO(content)

    if not is_csv_slot:
        # Tenta ler como XLSX (esperado para "FULL")
        try:
            return pd.read_excel(content_io)
        except Exception as e:
            st.error(f"Erro: Arquivo FULL não é um XLSX válido. Detalhes: {e}")
            return None

    # --- Lógica de Leitura CSV (Para EXT e FISICO) ---
    
    # 1. Tenta ler com separador PONTO-E-VÍRGULA (Padrão brasileiro)
    try:
        content_io.seek(0) 
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=';', 
            decimal=',',
            on_bad_lines='skip'
        )
        if df.shape[1] > 1: return df
    except:
        pass 

    # 2. Tenta ler com separador VÍRGULA (Padrão internacional)
    try:
        content_io.seek(0)
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=',', 
            decimal='.', 
            on_bad_lines='skip'
        )
        if df.shape[1] > 1: return df
    except Exception as e:
        pass 

    # Se falhar as duas tentativas
    st.error(f"Erro Crítico: Arquivo {tipo_arquivo} (CSV) falhou. Detalhes: {e}")
    return None

# --- Funções de Cache de Dados ---

@st.cache_data(ttl=600)
def get_relatorio_full(empresa):
    """Carrega o relatório FULL (XLSX)"""
    return read_file_from_storage(empresa, "FULL")

@st.cache_data(ttl=600)
def get_vendas_externas(empresa):
    """Carrega Vendas Externas (CSV)"""
    return read_file_from_storage(empresa, "EXT")

@st.cache_data(ttl=600)
def get_estoque_fisico(empresa):
    """Carrega Estoque Físico (CSV)"""
    return read_file_from_storage(empresa, "FISICO")

# --- Função de cálculo principal ---

def calcular_reposicao(empresa):
    # Garante que o catálogo foi carregado
    if 'catalogo_dados' not in st.session_state or st.session_state['catalogo_dados'] is None:
        st.error("ERRO: O Catálogo Padrão (KITS/CATALOGO) não foi carregado. Clique no botão na sidebar.")
        return None
        
    df_full = get_relatorio_full(empresa)
    df_ext = get_vendas_externas(empresa)
    df_fisico = get_estoque_fisico(empresa)
    catalogo = st.session_state['catalogo_dados']

    if df_full is None or df_ext is None or df_fisico is None:
        st.warning("Um ou mais arquivos de base estão faltando ou com erro. Reposição não calculada.")
        return None

    # Lógica de Merge e Cálculo V45/V46
    
    st.success("Arquivos base carregados e Catálogo pronto. Inicie o processamento da reposição.")
    # A função deve retornar o DataFrame de resultado da reposição
    return df_full