import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

def find_header_and_read(content_io, keywords=['sku', 'codigo', 'item', 'referencia']):
    """Busca a linha do cabeçalho varrendo o arquivo até encontrar as palavras-chave."""
    try:
        # Tenta ler as primeiras 20 linhas para encontrar o cabeçalho real
        df_temp = pd.read_excel(content_io, header=None, nrows=20)
        header_row = 0
        for i, row in df_temp.iterrows():
            # Converte a linha inteira em uma string minuscula para busca
            line_str = " ".join([str(val).lower() for val in row.values if pd.notnull(val)])
            if any(k in line_str for k in keywords):
                header_row = i
                break
        
        content_io.seek(0)
        return pd.read_excel(content_io, skiprows=header_row)
    except Exception as e:
        try: # Fallback para CSV
            content_io.seek(0)
            return pd.read_csv(content_io, sep=None, engine='python', encoding='utf-8-sig')
        except:
            return None

def read_file_from_storage(empresa, tipo_arquivo):
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if not content: return None
    
    df = find_header_and_read(io.BytesIO(content))
    if df is not None:
        df = utils.normalize_cols(df)
        # Identifica a coluna de SKU de forma agressiva
        for col in df.columns:
            if any(k == col or k in col for k in ['sku', 'codigo', 'cod', 'item', 'referencia']):
                df.rename(columns={col: 'sku'}, inplace=True)
                break
        if 'sku' in df.columns:
            df['sku'] = df['sku'].astype(str).apply(utils.norm_sku)
            return df
    return None

def flex_col(df, keywords):
    """Retorna o nome da coluna que contém uma das palavras-chave."""
    for k in keywords:
        for col in df.columns:
            if k in str(col).lower(): return col
    return None

def explodir_vendas(df_vendas, df_kits, col_venda):
    if df_vendas is None or df_vendas.empty or df_kits is None or df_kits.empty:
        return pd.DataFrame(columns=['sku', col_venda])
    
    df_merge = pd.merge(df_vendas, df_kits, left_on='sku', right_on='sku_kit', how='inner')
    df_merge['v_calc'] = df_merge[col_venda] * df_merge['quantidade_componente'].fillna(1).astype(float)
    df_exp = df_merge.groupby('sku_componente')['v_calc'].sum().reset_index()
    df_exp.rename(columns={'sku_componente': 'sku', 'v_calc': col_venda}, inplace=True)
    return df_exp

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    df_full = read_file_from_storage(empresa, "FULL")
    df_ext = read_file_from_storage(empresa, "EXT")
    df_fisico = read_file_from_storage(empresa, "FISICO")
    
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    df_catalogo = dados_cat['catalogo'].copy()
    df_kits = dados_cat['kits'].copy()

    # 1. PROCESSAMENTO FULL (MERCADO LIVRE)
    v_full_map = pd.DataFrame(columns=['sku', 'v_f_u', 'e_f_u'])
    if df_full is not None and not df_full.empty:
        v_col = flex_col(df_full, ['venda_60', 'venda_61', 'venda_qtd', 'venda'])
        e_col = flex_col(df_full, ['disponivel', 'estoque_atual', 'estoque_total', 'estoque'])
        
        if v_col and e_col:
            df_full['v_f_u'] = df_full[v_col].apply(utils.br_to_float).fillna(0)
            df_f_exp = explodir_vendas(df_full[['sku', 'v_f_u']], df_kits, 'v_f_u')
            v_f_total = pd.concat([df_full[['sku', 'v_f_u']], df_f_exp]).groupby('sku')['v_f_u'].sum().reset_index()
            e_f_total = df_full.groupby('sku')[e_col].sum().reset_index().rename(columns={e_col: 'e_f_u'})
            v_full_map = pd.merge(v_f_total, e_f_total, on='sku', how='outer').fillna(0)

    # 2. PROCESSAMENTO SHOPEE
    v_shopee_map = pd.DataFrame(columns=['sku', 'v_s_u'])
    if df_ext is not None and not df_ext.empty:
        v_col_s = flex_col(df_ext, ['venda', 'qtde', 'qtd', 'quantidade'])
        if v_col_s:
            df_ext['v_s_u'] = df_ext[v_col_s].apply(utils.br_to_float).fillna(0)
            df_s_exp = explodir_vendas(df_ext[['sku', 'v_s_u']], df_kits, 'v_s_u')
            v_shopee_map = pd.concat([df_ext[['sku', 'v_s_u']], df_s_exp]).groupby('sku')['v_s_u'].sum().reset_index()

    # 3. PROCESSAMENTO FÍSICO
    est_map = pd.DataFrame(columns=['sku', 'est_f_u', 'c_u'])
    if df_fisico is not None and not df_fisico.empty:
        e_col_f = flex_col(df_fisico, ['estoque', 'saldo', 'fisico', 'atual'])
        p_col_f = flex_col(df_fisico, ['preco', 'custo', 'compra', 'valor_unitario'])
        if e_col_f and p_col_f:
            df_fisico['est_f_u'] = df_fisico[e_col_f].apply(utils.br_to_float).fillna(0)
            df_fisico['c_u'] = df_fisico[p_col_f].apply(utils.br_to_float).fillna(0)
            est_map = df_fisico.groupby('sku').agg({'est_f_u': 'sum', 'c_u': 'max'}).reset_index()

    # 4. MERGE E CÁLCULOS
    df_res = pd.merge(df_catalogo, v_full_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res = pd.merge(df_res, est_map, on='sku', how='left')
    df_res.fillna(0, inplace=True)

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

    # 5. FILTRO DE STATUS (CORREÇÃO DO ATTRIBUTEERROR)
    st_col = flex_col(df_res, ['status_reposicao', 'status_repor'])
    if st_col and st_col in df_res.columns:
        # Filtra apenas se a coluna existir e tiver dados
        df_res = df_res[df_res[st_col].astype(str).str.lower().str.strip() != 'nao_repor']
    
    if not df_kits.empty:
        df_res = df_res[~df_res['sku'].isin(df_kits['sku_kit'].unique())]

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'c_u': 'Preço de custo',
        'v_f_u': 'Vendas full', 'v_s_u': 'vendas Shopee',
        'e_f_u': 'Estoque full (Un)', 'est_f_u': 'Estoque fisico (Un)'
    })