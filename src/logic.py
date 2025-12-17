import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# Funções de leitura (CONGELADAS)
def get_relatorio_full(empresa): return read_file_from_storage(empresa, "FULL")
def get_vendas_externas(empresa): return read_file_from_storage(empresa, "EXT")
def get_estoque_fisico(empresa): return read_file_from_storage(empresa, "FISICO")

def read_file_from_storage(empresa, tipo_arquivo):
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if not content: return None
    content_io = io.BytesIO(content)
    skip = 2 if tipo_arquivo == "FULL" else 0
    try:
        df = pd.read_excel(content_io, skiprows=skip)
        df.columns = [str(c).strip().lower() for c in df.columns]
        sku_col = next((c for c in df.columns if 'sku' in c or 'codigo' in c), None)
        if sku_col: df.rename(columns={sku_col: 'sku'}, inplace=True)
        if 'sku' in df.columns:
            df['sku'] = df['sku'].astype(str).str.strip().str.upper()
        return df
    except: return None

# Explosão de Kits: Transforma venda de Kit em venda de Componente
def explodir_vendas(df_vendas, df_kits, col_venda):
    if df_vendas is None or df_vendas.empty or df_kits is None or df_kits.empty:
        return pd.DataFrame(columns=['sku', col_venda])
    df_merge = pd.merge(df_vendas, df_kits, left_on='sku', right_on='sku_kit', how='inner')
    df_merge['v_calc'] = df_merge[col_venda] * df_merge['quantidade_componente'].fillna(1).astype(float)
    df_exp = df_merge.groupby('sku_componente')['v_calc'].sum().reset_index()
    df_exp.rename(columns={'sku_componente': 'sku', 'v_calc': col_venda}, inplace=True)
    return df_exp

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. CARGA
    df_full_raw = get_relatorio_full(empresa)      
    df_ext_raw = get_vendas_externas(empresa)      
    df_fisico_raw = get_estoque_fisico(empresa)    
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    
    df_catalogo = dados_cat['catalogo'].copy()
    df_kits = dados_cat['kits'].copy()

    # 2. VENDAS FULL (ML) + EXPLOSÃO
    v_full_map = pd.DataFrame(columns=['sku', 'v_f_u', 'e_f_u'])
    if df_full_raw is not None and not df_full_raw.empty:
        v_col = next((c for c in df_full_raw.columns if 'venda' in c and 'qtd' in c), df_full_raw.columns[-1])
        e_col = next((c for c in df_full_raw.columns if 'estoque' in c or 'dispon' in c), df_full_raw.columns[-2])
        df_full_raw['v_f_u'] = df_full_raw[v_col].apply(utils.br_to_float).fillna(0)
        df_f_exp = explodir_vendas(df_full_raw[['sku', 'v_f_u']], df_kits, 'v_f_u')
        v_f_total = pd.concat([df_full_raw[['sku', 'v_f_u']], df_f_exp]).groupby('sku')['v_f_u'].sum().reset_index()
        e_f_total = df_full_raw.groupby('sku')[e_col].sum().reset_index().rename(columns={e_col: 'e_f_u'})
        v_full_map = pd.merge(v_f_total, e_f_total, on='sku', how='outer').fillna(0)

    # 3. VENDAS SHOPEE + EXPLOSÃO
    v_shopee_map = pd.DataFrame(columns=['sku', 'v_s_u'])
    if df_ext_raw is not None and not df_ext_raw.empty:
        v_col_s = next((c for c in df_ext_raw.columns if 'venda' in c or 'qtde' in c), df_ext_raw.columns[-1])
        df_ext_raw['v_s_u'] = df_ext_raw[v_col_s].apply(utils.br_to_float).fillna(0)
        df_s_exp = explodir_vendas(df_ext_raw[['sku', 'v_s_u']], df_kits, 'v_s_u')
        v_shopee_map = pd.concat([df_ext_raw[['sku', 'v_s_u']], df_s_exp]).groupby('sku')['v_s_u'].sum().reset_index()

    # 4. ESTOQUE FÍSICO (JACA)
    est_map = pd.DataFrame(columns=['sku', 'est_f_u', 'c_u'])
    if df_fisico_raw is not None and not df_fisico_raw.empty:
        e_col_f = next((c for c in df_fisico_raw.columns if 'estoque' in c), df_fisico_raw.columns[-1])
        p_col_f = next((c for c in df_fisico_raw.columns if 'preco' in c or 'custo' in c), df_fisico_raw.columns[-2])
        df_fisico_raw['est_f_u'] = df_fisico_raw[e_col_f].apply(utils.br_to_float).fillna(0)
        df_fisico_raw['c_u'] = df_fisico_raw[p_col_f].apply(utils.br_to_float).fillna(0)
        est_map = df_fisico_raw.groupby('sku').agg({'est_f_u': 'sum', 'c_u': 'max'}).reset_index()

    # 5. MERGE E CÁLCULO DE CANAIS SEPARADOS
    df_res = pd.merge(df_catalogo, v_full_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res = pd.merge(df_res, est_map, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    # 6. REGRAS DE CANAL (CAIXINHAS)
    fator = (1 + (crescimento/100))
    v_dia_f = (df_res['v_f_u'] * fator) / 60
    nec_f = (v_dia_f * (dias_cobertura + lead_time)) - df_res['e_f_u']
    df_res['Sugerido_Full'] = nec_f.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    
    v_dia_s = (df_res['v_s_u'] * fator) / 60
    nec_s = (v_dia_s * (dias_cobertura + lead_time)) - df_res['est_f_u']
    df_res['Sugerido_Fisico'] = nec_s.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)

    df_res['Compra sugerida'] = df_res['Sugerido_Full'] + df_res['Sugerido_Fisico']
    df_res['Valor total da compra sugerida'] = df_res['Compra sugerida'] * df_res['c_u']
    df_res['Valor Estoque Full'] = df_res['e_f_u'] * df_res['c_u']
    df_res['Valor Estoque Fisico'] = df_res['est_f_u'] * df_res['c_u']

    # Filtros e Remoção de KITS
    st_col = next((c for c in df_res.columns if 'status' in c or 'repor' in c), None)
    if st_col:
        df_res = df_res[df_res[st_col].astype(str).str.lower().str.strip() != 'nao_repor']
    if not df_kits.empty:
        df_res = df_res[~df_res['sku'].isin(df_kits['sku_kit'].unique())]

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'c_u': 'Preço de custo',
        'v_f_u': 'Vendas full', 'v_s_u': 'vendas Shopee',
        'e_f_u': 'Estoque full (Un)', 'est_f_u': 'Estoque fisico (Un)'
    })