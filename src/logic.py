import pandas as pd
import streamlit as st
import io
import numpy as np
# Importa módulos auxiliares necessários
from src import storage, utils 

# --- FUNÇÕES DE LEITURA DO SUPABASE (AUDITADO PARA CSV) ---

def read_file_from_storage(empresa, tipo_arquivo):
    """Lê e processa arquivos XLSX ou CSV baixados do Supabase."""
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    
    # Simula o download. Se o seu storage.py estiver ok, esta linha funciona.
    content = storage.download(path)
    if content is None:
        st.warning(f"Arquivo {tipo_arquivo} da {empresa} não encontrado ou vazio.")
        return None

    is_csv_slot = tipo_arquivo.upper() in ["EXT", "FISICO"] 
    content_io = io.BytesIO(content)

    if not is_csv_slot:
        # Leitura de XLSX (para o FULL)
        try:
            return utils.normalize_cols(pd.read_excel(content_io))
        except Exception:
            return None

    # --- Lógica de Leitura CSV (PARA EXT e FISICO) ---
    
    # Tenta ler com separador PONTO-E-VÍRGULA (Padrão brasileiro, mais seguro)
    try:
        content_io.seek(0) 
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=';', 
            decimal=',',
            thousands='.', # NOVO: Ajuda a ler números como "1.701,65"
            header=2, 
            on_bad_lines='skip'
        )
        if df.shape[1] > 1 and 'SKU' in df.columns: 
            return utils.normalize_cols(df)
    except:
        pass # Falha, tenta o próximo formato
        
    # Tenta ler com separador VÍRGULA (Formato do snippet, requer engine='python')
    try:
        content_io.seek(0)
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=',', 
            decimal=',',
            thousands='.', # NOVO
            engine='python', # NOVO: Usa o engine Python para melhor leitura de aspas/delimitadores complexos
            header=2,
            on_bad_lines='skip'
        )
        if df.shape[1] > 1 and 'SKU' in df.columns: 
            return utils.normalize_cols(df)
    except:
        pass # Falhou todos
        
    # Último recurso se tudo falhar (Retorna o Erro Crítico)
    st.error(f"Erro Crítico: Falha ao ler arquivo {tipo_arquivo} (CSV). Verifique o formato.")
    return None


# --- FUNÇÕES WRAPPER DE ACESSO AOS DADOS (USADAS PELO src/data.py) ---

@st.cache_data(ttl=600)
def get_relatorio_full(empresa):
    return read_file_from_storage(empresa, "FULL")

@st.cache_data(ttl=600)
def get_vendas_externas(empresa):
    return read_file_from_storage(empresa, "EXT")

@st.cache_data(ttl=600)
def get_estoque_fisico(empresa):
    return read_file_from_storage(empresa, "FISICO")


# --- FUNÇÃO PRINCIPAL DE CÁLCULO (A LÓGICA DE COMPRA) ---

def calcular_reposicao(empresa, bases):
    """
    Função principal que orquestra a lógica de reposição.
    Recebe o nome da empresa e o dicionário de bases completo.
    """
    df_kits = bases['catalogo_kits']
    df_catalogo_simples = bases['catalogo_simples']
    df_full = bases['df_full']
    df_fisico = bases['df_fisico']
    
    # Verificação de colunas mínimas (Ajustar conforme o seu real df_fisico/df_full)
    if 'sku' not in df_fisico.columns:
        st.error(f"Erro: A base de Estoque {empresa} não contém a coluna 'sku'.")
        return None
    if 'sku' not in df_full.columns:
        st.error(f"Erro: A base de Vendas {empresa} não contém a coluna 'sku'.")
        return None
    
    st.info("Explosão de kits e merges em andamento...")
    
    # --- 1. EXPLOSÃO DE KITS (Lógica placeholder) ---
    # Implementar a lógica real de explosão de kits se houver (Merge df_fisico com df_kits)
    
    # 2. MERGE: Unir Estoque (FISICO) com Vendas (FULL) e Preços (CATALOGO)
    
    # Merge com o Full (para Vendas 60d, etc.)
    df_final = pd.merge(
        df_fisico, 
        df_full[['sku', 'vendas_qtd_61d', 'vendas_valor_r$']], # Colunas do Full (devem ser normalizadas)
        on='sku', 
        how='left'
    )
    
    # Merge com o Catálogo (para Preço de Custo)
    df_final = pd.merge(
        df_final, 
        df_catalogo_simples[['sku', 'custo_medio']], # Colunas do Catálogo
        on='sku', 
        how='left'
    )
    
    # 3. TRATAMENTO E CÁLCULO DE REPOSIÇÃO
    
    df_final['Estoque_Fisico'] = df_final['estoque_atual'] # Ajuste de nome
    df_final['Vendas_60d'] = df_final['vendas_qtd_61d'].fillna(0)
    df_final['Preco_Custo'] = df_final['custo_medio'].apply(utils.br_to_float)
    df_final['Vendas_60d'] = df_final['Vendas_60d'].astype(int)

    # Lógica de falta (Exemplo)
    df_final['Faltam'] = np.where(
        (df_final['Estoque_Fisico'] - df_final['Vendas_60d'] / 60 * 30) < 0,
        (df_final['Vendas_60d'] / 60 * 30) - df_final['Estoque_Fisico'],
        0
    )
    df_final['Compra_Sugerida'] = np.ceil(df_final['Faltam']).astype(int)
    df_final['Valor_Compra_R$'] = df_final['Compra_Sugerida'] * df_final['Preco_Custo'].fillna(0)

    df_final['Empresa'] = empresa
    
    return df_final.filter(regex='(sku|Empresa|Estoque_|Vendas_|Preco_|Compra_|Valor_|Faltam)', axis=1)