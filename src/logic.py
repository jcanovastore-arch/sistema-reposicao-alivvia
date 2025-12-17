import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils # utils deve ter normalize_cols e br_to_float

# --- FUNÇÕES DE LEITURA DO SUPABASE (Com correção de header=2 para CSV) ---

def read_file_from_storage(empresa, tipo_arquivo):
    """Lê e processa arquivos XLSX ou CSV baixados do Supabase."""
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if content is None:
        return None

    is_csv_slot = tipo_arquivo.upper() in ["EXT", "FISICO"] 
    content_io = io.BytesIO(content)

    if not is_csv_slot:
        try:
            return pd.read_excel(content_io)
        except Exception:
            return None

    # --- Lógica de Leitura CSV ---
    try:
        content_io.seek(0) 
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=';', 
            decimal=',',
            header=2, # <-- CORREÇÃO: CABEÇALHO NA 3ª LINHA
            on_bad_lines='skip'
        )
        if df.shape[1] > 1 and 'SKU' in df.columns: 
            return utils.normalize_cols(df)
    except:
        pass
        
    try:
        content_io.seek(0)
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=',', 
            decimal='.',
            header=2, # <-- CORREÇÃO: CABEÇALHO NA 3ª LINHA
            on_bad_lines='skip'
        )
        if df.shape[1] > 1 and 'SKU' in df.columns: 
            return utils.normalize_cols(df)
    except:
        pass

    st.warning(f"Erro Crítico: Falha ao ler arquivo {tipo_arquivo} (CSV). Verifique o formato.")
    return None


# --- FUNÇÕES WRAPPER DE ACESSO AOS DADOS ---

@st.cache_data(ttl=600)
def get_relatorio_full(empresa):
    return read_file_from_storage(empresa, "FULL")

@st.cache_data(ttl=600)
def get_vendas_externas(empresa):
    return read_file_from_storage(empresa, "EXT")

@st.cache_data(ttl=600)
def get_estoque_fisico(empresa):
    return read_file_from_storage(empresa, "FISICO")


# --- FUNÇÃO PRINCIPAL DE CÁLCULO (ASSINATURA SIMPLIFICADA) ---

def calcular_reposicao(empresa, bases):
    """
    Função principal que orquestra a lógica de reposição.
    Recebe o nome da empresa e o dicionário de bases completo.
    """
    df_kits = bases['catalogo_kits']
    df_catalogo_simples = bases['catalogo_simples']
    df_full = bases['df_full']
    df_fisico = bases['df_fisico']
    
    # 1. EXPLOSÃO DE KITS (Lógica placeholder, mas funcional)
    # ...
    
    # 2. MERGE: Unir Estoque (FISICO) com Vendas (FULL) e Preços (CATALOGO)
    df_final = pd.merge(
        df_fisico, 
        df_full[['sku', 'vendas_qtd_61d', 'vendas_valor_r$']], 
        on='sku', 
        how='left'
    )
    
    df_final = pd.merge(
        df_final, 
        df_catalogo_simples[['sku', 'custo_medio']], 
        on='sku', 
        how='left'
    )
    
    # 3. CÁLCULO DE REPOSIÇÃO (Placeholder)
    df_final['custo_medio'] = df_final['custo_medio'].apply(utils.br_to_float)
    df_final['vendas_qtd_61d'] = df_final['vendas_qtd_61d'].fillna(0).astype(int)
    
    df_final['Estoque_Fisico'] = df_final['estoque_atual'] # Corrigindo nome
    df_final['Vendas_60d'] = df_final['vendas_qtd_61d']
    df_final['Preco_Custo'] = df_final['custo_medio']

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