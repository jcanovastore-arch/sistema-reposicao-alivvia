import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# --- FUNÇÕES DE LEITURA (CONGELADAS) ---
def get_relatorio_full(empresa): return read_file_from_storage(empresa, "FULL")
def get_vendas_externas(empresa): return read_file_from_storage(empresa, "EXT")
def get_estoque_fisico(empresa): return read_file_from_storage(empresa, "FISICO")

def read_file_from_storage(empresa, tipo_arquivo):
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if content is None: return None
    content_io = io.BytesIO(content)
    skip = 2 if tipo_arquivo == "FULL" else 0
    try:
        try:
            df = pd.read_excel(content_io, skiprows=skip)
        except:
            content_io.seek(0)
            df = pd.read_csv(content_io, skiprows=skip, sep=None, engine='python', encoding='utf-8-sig')
        df = utils.normalize_cols(df)
        for col in df.columns:
            if col in ['sku', 'codigo_sku', 'sku_id', 'codigo']:
                df.rename(columns={col: 'sku'}, inplace=True)
                break
        if 'sku' in df.columns:
            df['sku'] = df['sku'].apply(utils.norm_sku)
        return df
    except: return None

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. CARGA DE DADOS (CONGELADA)
    df_full = get_relatorio_full(empresa)      
    df_ext = get_vendas_externas(empresa)      
    df_fisico = get_estoque_fisico(empresa)    
    
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    
    # Catálogo original com a coluna 'status_reposicao'
    df_catalogo = dados_cat['catalogo'].copy()
    df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)

    # 2. PROCESSAMENTO ESTOQUE E VENDAS (CONGELADO)
    if df_fisico is not None and 'sku' in df_fisico.columns:
        df_fisico['est_f'] = df_fisico['estoque_atual'].apply(utils.br_to_float).fillna(0)
        df_fisico['custo'] = df_fisico['preco'].apply(utils.br_to_float).fillna(0)
        est_f_map = df_fisico.groupby('sku').agg({'est_f': 'sum', 'custo': 'max'}).reset_index()
    else:
        est_f_map = pd.DataFrame(columns=['sku', 'est_f', 'custo'])

    if df_full is not None and 'sku' in df_full.columns:
        df_full['v_f'] = df_full['vendas_qtd_61d'].apply(utils.br_to_float).fillna(0)
        df_full['e_f'] = df_full['estoque_atual'].apply(utils.br_to_float).fillna(0)
        v_full_map = df_full.groupby('sku').agg({'v_f': 'sum', 'e_f': 'sum'}).reset_index()
    else:
        v_full_map = pd.DataFrame(columns=['sku', 'v_f', 'e_f'])

    if df_ext is not None and 'sku' in df_ext.columns:
        v_col = 'qtde_vendas' if 'qtde_vendas' in df_ext.columns else df_ext.columns[min(2, len(df_ext.columns)-1)]
        df_ext['v_s'] = df_ext[v_col].apply(utils.br_to_float).fillna(0)
        v_shopee_map = df_ext.groupby('sku').agg({'v_s': 'sum'}).reset_index()
    else:
        v_shopee_map = pd.DataFrame(columns=['sku', 'v_s'])

    # 3. MERGE E CÁLCULOS (CONGELADOS)
    df_res = pd.merge(df_catalogo, est_f_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_full_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    df_res['Venda_Diaria'] = ((df_res['v_f'] + df_res['v_s']) * (1 + (crescimento/100))) / 60
    df_res['Estoque_Total_Qtd'] = df_res['est_f'] + df_res['e_f']
    compra = (df_res['Venda_Diaria'] * (dias_cobertura + lead_time)) - df_res['Estoque_Total_Qtd']
    df_res['Compra sugerida'] = compra.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    df_res['Valor total da compra sugerida'] = df_res['Compra sugerida'] * df_res['custo']
    df_res['Valor Estoque Full'] = df_res['e_f'] * df_res['custo']
    df_res['Valor Estoque Fisico'] = df_res['est_f'] * df_res['custo']

    # --- FILTRO DE SEGURANÇA: status_reposicao ---
    if 'status_reposicao' in df_res.columns:
        # Remove do sistema tudo que estiver marcado como 'nao_repor'
        df_res = df_res[df_res['status_reposicao'].astype(str).str.lower().str.strip() != 'nao_repor']

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'custo': 'Preço de custo',
        'v_f': 'Vendas full', 'v_s': 'vendas Shopee',
        'e_f': 'Estoque full (Un)', 'est_f': 'Estoque fisico (Un)'
    })