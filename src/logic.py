import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

def find_header_and_read(content_io, keywords=['sku', 'codigo', 'item', 'referencia']):
    try:
        df_temp = pd.read_excel(content_io, header=None, nrows=20)
        header_row = 0
        for i, row in df_temp.iterrows():
            line_str = " ".join([str(val).lower() for val in row.values if pd.notnull(val)])
            if any(k in line_str for k in keywords):
                header_row = i
                break
        content_io.seek(0)
        return pd.read_excel(content_io, skiprows=header_row)
    except:
        try:
            content_io.seek(0)
            return pd.read_csv(content_io, sep=None, engine='python', encoding='utf-8-sig')
        except: return None

def read_file_from_storage(empresa, tipo_arquivo):
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if not content: return None
    df = find_header_and_read(io.BytesIO(content))
    if df is not None:
        df = utils.normalize_cols(df)
        for col in df.columns:
            if any(k == col or k in col for k in ['sku', 'codigo', 'cod', 'item', 'referencia']):
                df.rename(columns={col: 'sku'}, inplace=True)
                break
        if 'sku' in df.columns:
            df['sku'] = df['sku'].astype(str).apply(utils.norm_sku)
            return df
    return None

def flex_col(df, keywords):
    if df is None or df.empty: return None
    for k in keywords:
        for col in df.columns:
            if k in str(col).lower(): return col
    return None

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. CARGA DE DADOS
    df_full_raw = read_file_from_storage(empresa, "FULL")
    df_ext_raw = read_file_from_storage(empresa, "EXT")
    df_fisico_raw = read_file_from_storage(empresa, "FISICO")
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    df_catalogo = dados_cat['catalogo'].copy()
    df_kits = dados_cat['kits'].copy()
    
    fator = (1 + (crescimento/100))
    prazo_total = dias_cobertura + lead_time

    # 2. CÁLCULO FULL (ANÚNCIO POR ANÚNCIO - REGRA DAS CAIXINHAS)
    nec_reposicao_full = pd.DataFrame(columns=['sku', 'v_f_u', 'e_f_u', 'nec_full'])
    if df_full_raw is not None and not df_full_raw.empty:
        v_col = flex_col(df_full_raw, ['venda_60', 'venda_61', 'venda_qtd', 'venda'])
        e_col = flex_col(df_full_raw, ['disponivel', 'estoque_atual', 'estoque_total', 'estoque'])
        
        if v_col and e_col:
            df_full_raw['v_un'] = df_full_raw[v_col].apply(utils.br_to_float).fillna(0)
            df_full_raw['e_un'] = df_full_raw[e_col].apply(utils.br_to_float).fillna(0)
            
            # Necessidade individual do anúncio
            v_dia = (df_full_raw['v_un'] * fator) / 60
            df_full_raw['falta'] = ((v_dia * prazo_total) - df_full_raw['e_un']).clip(lower=0)
            
            # Explosão de Kits no Full
            df_f_exp = pd.merge(df_full_raw, df_kits, left_on='sku', right_on='sku_kit', how='left')
            df_f_exp['sku_comp'] = df_f_exp['sku_componente'].fillna(df_f_exp['sku'])
            df_f_exp['qty_comp'] = df_f_exp['quantidade_componente'].fillna(1)
            
            df_f_exp['v_comp'] = df_f_exp['v_un'] * df_f_exp['qty_comp']
            df_f_exp['nec_comp'] = df_f_exp['falta'] * df_f_exp['qty_comp']
            
            nec_reposicao_full = df_f_exp.groupby('sku_comp').agg({
                'v_comp': 'sum', 'e_un': 'sum', 'nec_comp': 'sum'
            }).reset_index().rename(columns={'sku_comp': 'sku', 'v_comp': 'v_f_u', 'e_un': 'e_f_u', 'nec_comp': 'nec_full'})

    # 3. CÁLCULO SHOPEE (EXPLOSÃO DE KITS)
    v_shopee_map = pd.DataFrame(columns=['sku', 'v_s_u', 'dem_s'])
    if df_ext_raw is not None and not df_ext_raw.empty:
        v_col_s = flex_col(df_ext_raw, ['venda', 'qtde', 'qtd', 'quantidade'])
        if v_col_s:
            df_ext_raw['v_un_s'] = df_ext_raw[v_col_s].apply(utils.br_to_float).fillna(0)
            df_s_exp = pd.merge(df_ext_raw, df_kits, left_on='sku', right_on='sku_kit', how='left')
            df_s_exp['sku_comp'] = df_s_exp['sku_componente'].fillna(df_s_exp['sku'])
            df_s_exp['qty_comp'] = df_s_exp['quantidade_componente'].fillna(1)
            
            df_s_exp['v_comp_s'] = df_s_exp['v_un_s'] * df_s_exp['qty_comp']
            v_dia_s = (df_s_exp['v_comp_s'] * fator) / 60
            df_s_exp['dem_s_calc'] = v_dia_s * prazo_total
            
            v_shopee_map = df_s_exp.groupby('sku_comp').agg({
                'v_comp_s': 'sum', 'dem_s_calc': 'sum'
            }).reset_index().rename(columns={'sku_comp': 'sku', 'v_comp_s': 'v_s_u', 'dem_s_calc': 'dem_s'})

    # 4. ESTOQUE FÍSICO E CUSTO
    est_map = pd.DataFrame(columns=['sku', 'est_f_u', 'c_u'])
    if df_fisico_raw is not None and not df_fisico_raw.empty:
        e_col_f = flex_col(df_fisico_raw, ['estoque', 'saldo', 'fisico', 'atual'])
        p_col_f = flex_col(df_fisico_raw, ['preco', 'custo', 'compra', 'valor_unitario'])
        if e_col_f and p_col_f:
            df_fisico_raw['est_f_u'] = df_fisico_raw[e_col_f].apply(utils.br_to_float).fillna(0)
            df_fisico_raw['c_u'] = df_fisico_raw[p_col_f].apply(utils.br_to_float).fillna(0)
            est_map = df_fisico_raw.groupby('sku').agg({'est_f_u': 'sum', 'c_u': 'max'}).reset_index()

    # 5. MERGE FINAL E CÁLCULO DE COMPRA
    df_res = pd.merge(df_catalogo, nec_reposicao_full, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res = pd.merge(df_res, est_map, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    # Cálculo da Compra Sugerida (Falta no Full + Demanda Shopee - Saldo Físico)
    df_res['Compra sugerida'] = (df_res['nec_full'] + df_res['dem_s'] - df_res['est_f_u']).clip(lower=0).apply(np.ceil).astype(int)
    
    df_res['Valor total da compra sugerida'] = df_res['Compra sugerida'] * df_res['c_u']
    df_res['Valor Estoque Full'] = df_res['e_f_u'] * df_res['c_u']
    df_res['Valor Estoque Fisico'] = df_res['est_f_u'] * df_res['c_u']

    # 6. FILTRO DE STATUS (FIX PARA O ATTRIBUTEERROR)
    st_col = flex_col(df_res, ['status_reposicao', 'status_repor'])
    if st_col and st_col in df_res.columns:
        # Garantimos que tratamos como string antes de filtrar
        df_res[st_col] = df_res[st_col].astype(str).str.lower().str.strip()
        df_res = df_res[df_res[st_col] != 'nao_repor']
    
    if not df_kits.empty:
        df_res = df_res[~df_res['sku'].isin(df_kits['sku_kit'].unique())]

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'c_u': 'Preço de custo',
        'v_f_u': 'Vendas full', 'v_s_u': 'vendas Shopee',
        'e_f_u': 'Estoque full (Un)', 'est_f_u': 'Estoque fisico (Un)'
    })