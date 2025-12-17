import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

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
        if 'sku' in df.columns:
            df['sku'] = df['sku'].apply(utils.norm_sku)
        return df
    except:
        return None

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. Carregar Bases
    df_full = get_relatorio_full(empresa)      
    df_ext = get_vendas_externas(empresa)      
    df_fisico = get_estoque_fisico(empresa)    
    
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    df_catalogo = dados_cat['catalogo'].copy()
    df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)

    # 2. Tratamento Estoque Físico e Custo
    if df_fisico is not None and not df_fisico.empty:
        df_fisico['estoque_fisico'] = df_fisico['estoque_atual'].apply(utils.br_to_float).fillna(0)
        df_fisico['custo_unit'] = df_fisico['preco'].apply(utils.br_to_float).fillna(0)
        estoque_real = df_fisico.groupby('sku').agg({'estoque_fisico': 'sum', 'custo_unit': 'max'}).reset_index()
    else:
        estoque_real = pd.DataFrame(columns=['sku', 'estoque_fisico', 'custo_unit'])

    # 3. Tratamento Vendas Full (ML)
    if df_full is not None and not df_full.empty:
        df_full['v_full'] = df_full['vendas_qtd_61d'].apply(utils.br_to_float).fillna(0)
        df_full['e_full'] = df_full['estoque_atual'].apply(utils.br_to_float).fillna(0)
        vendas_full = df_full.groupby('sku').agg({'v_full': 'sum', 'e_full': 'sum'}).reset_index()
    else:
        vendas_full = pd.DataFrame(columns=['sku', 'v_full', 'e_full'])

    # 4. Tratamento Vendas Shopee (EXT)
    if df_ext is not None and not df_ext.empty:
        # Pega a coluna 'qtde_vendas' que vem do normalize_cols
        col_venda = 'qtde_vendas' if 'qtde_vendas' in df_ext.columns else df_ext.columns[2]
        df_ext['v_shopee'] = df_ext[col_venda].apply(utils.br_to_float).fillna(0)
        vendas_shopee = df_ext.groupby('sku').agg({'v_shopee': 'sum'}).reset_index()
    else:
        vendas_shopee = pd.DataFrame(columns=['sku', 'v_shopee'])

    # 5. MERGE FINAL
    df_res = df_catalogo[['sku', 'fornecedor']].copy()
    df_res = pd.merge(df_res, estoque_real, on='sku', how='left')
    df_res = pd.merge(df_res, vendas_full, on='sku', how='left')
    df_res = pd.merge(df_res, vendas_shopee, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    # 6. Cálculos
    df_res['Vendas_Total_60d'] = df_res['v_full'] + df_res['v_shopee']
    df_res['Venda_Diaria'] = (df_res['Vendas_Total_60d'] * (1 + (crescimento/100))) / 60
    df_res['Estoque_Total'] = df_res['estoque_fisico'] + df_res['e_full']
    
    df_res['Compra_Sugerida'] = (df_res['Venda_Diaria'] * (dias_cobertura + lead_time)) - df_res['Estoque_Total']
    df_res['Compra_Sugerida'] = df_res['Compra_Sugerida'].apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    df_res['Valor_Compra'] = df_res['Compra_Sugerida'] * df_res['custo_unit']

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'custo_unit': 'Preço de custo',
        'v_full': 'Vendas full', 'v_shopee': 'vendas Shopee',
        'e_full': 'Estoque full', 'estoque_fisico': 'Estoque fisico',
        'Compra_Sugerida': 'Compra sugerida', 'Valor_Compra': 'Valor total da compra sugerida'
    })