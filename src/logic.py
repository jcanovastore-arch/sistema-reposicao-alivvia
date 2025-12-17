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
    # Pula 2 linhas apenas no FULL do Mercado Livre
    skip = 2 if tipo_arquivo == "FULL" else 0
    
    try:
        try:
            df = pd.read_excel(content_io, skiprows=skip)
        except:
            content_io.seek(0)
            df = pd.read_csv(content_io, skiprows=skip, sep=None, engine='python', encoding='utf-8-sig')
        
        return utils.normalize_cols(df)
    except Exception as e:
        return None

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. Carregar Bases do Storage
    df_full = get_relatorio_full(empresa)
    df_ext = get_vendas_externas(empresa)
    df_fisico = get_estoque_fisico(empresa)
    
    # Busca Catálogo do Session State
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    df_catalogo = dados_cat['catalogo']

    # 2. Tratamento Estoque Físico e Custo (Jaca-Estoque)
    if df_fisico is not None:
        # 'estoque_atual' e 'preco' são os nomes normalizados pelo utils.py
        df_fisico['estoque_fisico'] = df_fisico['estoque_atual'].apply(utils.br_to_float).fillna(0)
        df_fisico['custo_unit'] = df_fisico['preco'].apply(utils.br_to_float).fillna(0)
        estoque_real = df_fisico.groupby('codigo_sku').agg({'estoque_fisico': 'sum', 'custo_unit': 'max'}).reset_index().rename(columns={'codigo_sku': 'sku'})
    else:
        estoque_real = pd.DataFrame(columns=['sku', 'estoque_fisico', 'custo_unit'])

    # 3. Tratamento Vendas Full (Mercado Livre)
    if df_full is not None:
        df_full['vendas_full_60d'] = df_full['vendas_qtd_61d'].apply(utils.br_to_float).fillna(0)
        df_full['estoque_full'] = df_full['estoque_atual'].apply(utils.br_to_float).fillna(0)
        v_full = df_full.groupby('sku').agg({'vendas_full_60d': 'sum', 'estoque_full': 'sum'}).reset_index()
    else:
        v_full = pd.DataFrame(columns=['sku', 'vendas_full_60d', 'estoque_full'])

    # 4. Tratamento Vendas Shopee (EXT)
    if df_ext is not None:
        # 'qtde_vendas' é o nome que o utils.py dá para 'Qtde. Vendas'
        df_ext['vendas_shopee_60d'] = df_ext['qtde_vendas'].apply(utils.br_to_float).fillna(0)
        v_ext = df_ext.groupby('sku').agg({'vendas_shopee_60d': 'sum'}).reset_index()
    else:
        v_ext = pd.DataFrame(columns=['sku', 'vendas_shopee_60d'])

    # 5. Cruzamento Final
    df_res = df_catalogo[['sku', 'fornecedor']].copy()
    df_res['sku'] = df_res['sku'].apply(utils.norm_sku)

    df_res = pd.merge(df_res, estoque_real, on='sku', how='left')
    df_res = pd.merge(df_res, v_full, on='sku', how='left')
    df_res = pd.merge(df_res, v_ext, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    # 6. Cálculos
    df_res['Vendas_Total_60d'] = df_res['vendas_full_60d'] + df_res['vendas_shopee_60d']
    df_res['Venda_Diaria'] = (df_res['Vendas_Total_60d'] * (1 + (crescimento/100))) / 60
    df_res['Estoque_Total'] = df_res['estoque_fisico'] + df_res['estoque_full']
    
    df_res['Compra_Sugerida'] = (df_res['Venda_Diaria'] * (dias_cobertura + lead_time)) - df_res['Estoque_Total']
    df_res['Compra_Sugerida'] = df_res['Compra_Sugerida'].apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    df_res['Valor_Compra'] = df_res['Compra_Sugerida'] * df_res['custo_unit']

    # Renomear para a Interface
    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'estoque_fisico': 'Estoque_Fisico',
        'estoque_full': 'Estoque_Full', 'vendas_full_60d': 'Vendas_Full_60d',
        'vendas_shopee_60d': 'Vendas_Shopee_60d', 'custo_unit': 'Preco_Custo'
    })