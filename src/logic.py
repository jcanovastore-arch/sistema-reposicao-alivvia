import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# --- FUNÇÕES DE LEITURA DO SUPABASE (AJUSTE FINAL DE PARSING) ---

def read_file_from_storage(empresa, tipo_arquivo):
    """Lê e processa arquivos XLSX ou CSV baixados do Supabase."""
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    
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
    
    # Tentativa 1 (Padrão: Vírgula, pulando 2 linhas) - A mais provável para o seu arquivo
    try:
        content_io.seek(0) 
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=',', 
            skiprows=2,     # <-- SOLUÇÃO FINAL: PULA AS 2 PRIMEIRAS LINHAS DE JUNK
            header=0,       # <-- LÊ A PRÓXIMA LINHA COMO CABEÇALHO
            engine='python', # Necessário para lidar com aspas e vírgulas complexas
            on_bad_lines='skip'
        )
        # Validação: se o DataFrame tem mais de 1 coluna e a coluna SKU existe (após normalização)
        if df.shape[1] > 1 and 'sku' in utils.normalize_cols(df).columns: 
            return utils.normalize_cols(df)
    except:
        pass 
        
    # Tentativa 2 (Padrão: Ponto-e-vírgula, pulando 2 linhas) - Backup
    try:
        content_io.seek(0)
        df = pd.read_csv(
            content_io, 
            encoding='latin1', 
            sep=';', 
            skiprows=2, 
            header=0,
            engine='python', 
            on_bad_lines='skip'
        )
        if df.shape[1] > 1 and 'sku' in utils.normalize_cols(df).columns: 
            return utils.normalize_cols(df)
    except:
        pass
        
    # Último recurso se tudo falhar
    st.error(f"Erro Crítico: Falha ao ler arquivo {tipo_arquivo} (CSV). Verifique o formato.")
    return None


# --- FUNÇÕES WRAPPER, CÁLCULO E LÓGICA (Mantenha o resto das funções aqui) ---
@st.cache_data(ttl=600)
def get_relatorio_full(empresa):
    return read_file_from_storage(empresa, "FULL")

@st.cache_data(ttl=600)
def get_vendas_externas(empresa):
    return read_file_from_storage(empresa, "EXT")

@st.cache_data(ttl=600)
def get_estoque_fisico(empresa):
    return read_file_from_storage(empresa, "FISICO")


def calcular_reposicao(empresa, bases):
    """
    Função principal que orquestra a lógica de reposição.
    """
    df_kits = bases['catalogo_kits']
    df_catalogo_simples = bases['catalogo_simples']
    df_full = bases['df_full']
    df_fisico = bases['df_fisico']
    
    # Verificação de colunas mínimas (Pode falhar se o SKU não for lido corretamente!)
    if 'sku' not in df_fisico.columns or 'sku' not in df_full.columns:
        st.error(f"Erro de Coluna: O arquivo da {empresa} não tem a coluna 'sku'. O arquivo não foi lido corretamente.")
        return None
    
    st.info("Explosão de kits e merges em andamento...")
    
    # 2. MERGE e CÁLCULO (Código da resposta anterior)
    
    # ... (O resto do código de merge e cálculo)
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
    
    df_final['Estoque_Fisico'] = df_final['estoque_atual']
    df_final['Vendas_60d'] = df_final['vendas_qtd_61d'].fillna(0)
    df_final['Preco_Custo'] = df_final['custo_medio'].apply(utils.br_to_float)
    df_final['Vendas_60d'] = df_final['Vendas_60d'].astype(int)

    df_final['Faltam'] = np.where(
        (df_final['Estoque_Fisico'] - df_final['Vendas_60d'] / 60 * 30) < 0,
        (df_final['Vendas_60d'] / 60 * 30) - df_final['Estoque_Fisico'],
        0
    )
    df_final['Compra_Sugerida'] = np.ceil(df_final['Faltam']).astype(int)
    df_final['Valor_Compra_R$'] = df_final['Compra_Sugerida'] * df_final['Preco_Custo'].fillna(0)

    df_final['Empresa'] = empresa
    
    return df_final.filter(regex='(sku|Empresa|Estoque_|Vendas_|Preco_|Compra_|Valor_|Faltam)', axis=1)