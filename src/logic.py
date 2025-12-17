import pandas as pd
import streamlit as st
import io
from src import storage, utils 

def get_relatorio_full(empresa): return read_file_from_storage(empresa, "FULL")
def get_vendas_externas(empresa): return read_file_from_storage(empresa, "EXT")
def get_estoque_fisico(empresa): return read_file_from_storage(empresa, "FISICO")

def read_file_from_storage(empresa, tipo_arquivo):
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if content is None: return None
    
    content_io = io.BytesIO(content)
    try:
        df = None
        # Define quantas linhas pular (FULL tem 2 linhas de cabeçalho inútil)
        skip = 2 if tipo_arquivo == "FULL" else 0
        
        # Tenta ler como Excel
        try:
            df = pd.read_excel(content_io, skiprows=skip)
        except:
            # Tenta ler como CSV (Seu caso atual)
            content_io.seek(0)
            try:
                df = pd.read_csv(content_io, encoding='utf-8-sig', sep=',', quotechar='"', skiprows=skip)
                if len(df.columns) <= 1: raise Exception()
            except:
                content_io.seek(0)
                df = pd.read_csv(content_io, encoding='latin1', sep=';', quotechar='"', skiprows=skip)

        # Normaliza
        df = utils.normalize_cols(df)
        
        # --- BLINDAGEM CONTRA ERROS ---
        # Se normalizou errado, força o nome certo
        if 'vendas_qtd_61d' in df.columns:
            df.rename(columns={'vendas_qtd_61d': 'vendas_qtd'}, inplace=True)

        if 'sku' not in df.columns:
            if 'codigo_sku' in df.columns: df.rename(columns={'codigo_sku': 'sku'}, inplace=True)
            else:
                st.error(f"❌ Erro {tipo_arquivo} ({empresa}): Coluna SKU não encontrada. Colunas: {list(df.columns)}")
                return None
        
        if tipo_arquivo == "FULL" and 'vendas_qtd' not in df.columns:
            st.error(f"❌ Erro {tipo_arquivo} ({empresa}): Coluna 'Vendas Qtd' não encontrada. Colunas: {list(df.columns)}")
            return None

        return df
    except Exception as e:
        st.error(f"Erro ao ler arquivo {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(df_full, df_fisico, df_ext, df_kits, df_catalogo, empresa):
    # Padroniza SKUs
    df_full['sku'] = df_full['sku'].apply(utils.norm_sku)
    df_fisico['sku'] = df_fisico['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
    
    # 1. Vendas
    vendas = df_full[['sku', 'vendas_qtd']].copy()
    if df_ext is not None and 'vendas_qtd' in df_ext.columns:
        v_ext = df_ext[['sku', 'vendas_qtd']].copy()
        vendas = pd.concat([vendas, v_ext])
    
    vendas_agrupadas = vendas.groupby('sku')['vendas_qtd'].sum().reset_index()

    # 2. Explosão de Kits
    v_com_kits = pd.merge(df_kits, vendas_agrupadas, left_on='sku_kit', right_on='sku', how='inner')
    v_com_kits['v_expl'] = v_com_kits['vendas_qtd'] * v_com_kits['quantidade_no_kit']
    v_expl_final = v_com_kits.groupby('sku_componente')['v_expl'].sum().reset_index().rename(columns={'sku_componente': 'sku'})

    # 3. Merge Final
    df_res = pd.merge(df_fisico[['sku', 'estoque_atual']], vendas_agrupadas, on='sku', how='left').fillna(0)
    df_res = pd.merge(df_res, v_expl_final, on='sku', how='left').fillna(0)
    df_res['Vendas_Total_60d'] = df_res['vendas_qtd'] + df_res['v_expl']
    
    # Custo
    df_res = pd.merge(df_res, df_catalogo[['sku', 'custo_medio', 'fornecedor']], on='sku', how='left')
    
    # Resultado
    df_res['Compra_Sugerida'] = (df_res['Vendas_Total_60d'] - df_res['estoque_atual']).clip(lower=0)
    df_res['Preco_Custo'] = df_res['custo_medio'].apply(utils.br_to_float)
    df_res['Valor_Sugerido_R$'] = df_res['Compra_Sugerida'] * df_res['Preco_Custo']
    
    return df_res.rename(columns={'sku': 'SKU', 'estoque_atual': 'Estoque_Fisico', 'fornecedor': 'Fornecedor'})