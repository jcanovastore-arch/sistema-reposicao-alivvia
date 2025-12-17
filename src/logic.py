import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils

# --- FUNÇÕES DE LEITURA DO SUPABASE (AUDITADO PARA CSV COM 3 LINHAS DE CABEÇALHO) ---

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
            # Leitura de XLSX (para o FULL)
            return pd.read_excel(content_io)
        except Exception:
            return None

    # --- Lógica de Leitura CSV (PARA EXT e FISICO) ---
    
    # Tentativa de ler com cabeçalho na linha 3 (header=2)
    # 1. Tenta ler com separador PONTO-E-VÍRGULA (Padrão brasileiro)
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
        # Se leu mais de 1 coluna, foi um sucesso.
        if df.shape[1] > 1 and 'SKU' in df.columns: 
            return utils.normalize_cols(df) # Normaliza as colunas lidas
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
            header=2, # <-- CORREÇÃO: CABEÇALHO NA 3ª LINHA
            on_bad_lines='skip'
        )
        if df.shape[1] > 1 and 'SKU' in df.columns: 
            return utils.normalize_cols(df) # Normaliza as colunas lidas
    except:
        pass

    st.warning(f"Erro Crítico: Falha ao ler arquivo {tipo_arquivo} (CSV). Verifique o formato.")
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

def calcular_reposicao(empresa, dados_catalogo, df_full, df_ext, df_fisico):
    """Função principal que orquestra a lógica de reposição."""
    
    df_kits = dados_catalogo['kits']
    df_catalogo_simples = dados_catalogo['catalogo']
    
    # 1. EXPLOSÃO DE KITS (Baseado no memorando)
    # Assumindo que o catálogo de kits tem as colunas 'sku_kit' e 'sku_componente'
    # Esta é uma simulação, ajuste conforme a sua lógica real de merge
    
    # 1.1. Normalizar colunas importantes (ex: SKU, Qtd)
    df_fisico = utils.normalize_cols(df_fisico)
    df_full = utils.normalize_cols(df_full)

    # 1.2. Mapeamento de kits
    # A lógica aqui é complexa e deve ser re-implementada com base na sua fórmula V45/V46.
    # Por enquanto, focamos apenas na unificação dos dados.
    
    # 2. MERGE: Unir Estoque (FISICO) com Vendas (FULL) e Preços (CATALOGO)
    
    # Merge com o Full (para Vendas 60d, etc.)
    df_final = pd.merge(
        df_fisico, 
        df_full[['sku', 'vendas_qtd_61d', 'vendas_valor_r$']], 
        on='sku', 
        how='left'
    )
    
    # Merge com o Catálogo (para Preço de Custo)
    df_final = pd.merge(
        df_final, 
        df_catalogo_simples[['sku', 'custo_medio']], 
        on='sku', 
        how='left'
    )
    
    df_final['custo_medio'] = df_final['custo_medio'].apply(utils.br_to_float)
    df_final['vendas_qtd_61d'] = df_final['vendas_qtd_61d'].fillna(0).astype(int)
    
    # Renomear colunas para o display final
    df_final = df_final.rename(columns={
        'estoque_atual': 'Estoque_Fisico',
        'vendas_qtd_61d': 'Vendas_60d',
        'custo_medio': 'Preco_Custo',
    })
    
    # 3. CÁLCULO DE REPOSIÇÃO (Placeholder para o ROP/Qtd Segura)
    df_final['Faltam'] = np.where(
        (df_final['Estoque_Fisico'] - df_final['Vendas_60d'] / 60 * 30) < 0,
        (df_final['Vendas_60d'] / 60 * 30) - df_final['Estoque_Fisico'],
        0
    )
    df_final['Compra_Sugerida'] = np.ceil(df_final['Faltam']).astype(int)
    
    df_final['Valor_Compra_R$'] = df_final['Compra_Sugerida'] * df_final['Preco_Custo'].fillna(0)

    # Adicionar coluna da Empresa para unificar os resultados
    df_final['Empresa'] = empresa
    
    return df_final.filter(regex='(sku|Empresa|Estoque_|Vendas_|Preco_|Compra_|Valor_|Faltam)', axis=1)