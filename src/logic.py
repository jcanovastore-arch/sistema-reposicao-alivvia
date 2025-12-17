import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# Funções de suporte (Lógica de leitura CONGELADA)
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
            if any(k in col for k in ['sku', 'codigo', 'item', 'referencia']):
                df.rename(columns={col: 'sku'}, inplace=True)
                break
        if 'sku' in df.columns:
            df['sku'] = df['sku'].apply(utils.norm_sku)
        return df
    except: return None

# Explosão de Kits (Para SKUs como HANDGRIP)
def explodir_vendas(df_vendas, df_kits, col_venda):
    if df_vendas is None or df_vendas.empty or df_kits is None or df_kits.empty:
        return pd.DataFrame(columns=['sku', col_venda])
    df_merge = pd.merge(df_vendas, df_kits, left_on='sku', right_on='sku_kit', how='inner')
    df_merge['v_calc'] = df_merge[col_venda] * df_merge['quantidade_componente'].fillna(1)
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

    # 2. VENDAS FULL + EXPLOSÃO
    if df_full_raw is not None and not df_full_raw.empty:
        df_full_raw['v_f_u'] = df_full_raw['vendas_qtd_61d'].apply(utils.br_to_float).fillna(0)
        df_f_exp = explodir_vendas(df_full_raw[['sku', 'v_f_u']], df_kits, 'v_f_u')
        v_f_total = pd.concat([df_full_raw[['sku', 'v_f_u']], df_f_exp]).groupby('sku')['v_f_u'].sum().reset_index()
        e_f_total = df_full_raw.groupby('sku')['estoque_atual'].sum().reset_index().rename(columns={'estoque_atual': 'e_f_u'})
        v_full_map = pd.merge(v_f_total, e_f_total, on='sku', how='outer').fillna(0)
    else:
        v_full_map = pd.DataFrame(columns=['sku', 'v_f_u', 'e_f_u'])

    # 3. VENDAS SHOPEE + EXPLOSÃO
    if df_ext_raw is not None and not df_ext_raw.empty:
        v_col = 'qtde_vendas' if 'qtde_vendas' in df_ext_raw.columns else df_ext_raw.columns[min(2, len(df_ext_raw.columns)-1)]
        df_ext_raw['v_s_u'] = df_ext_raw[v_col].apply(utils.br_to_float).fillna(0)
        df_s_exp = explodir_vendas(df_ext_raw[['sku', 'v_s_u']], df_kits, 'v_s_u')
        v_shopee_map = pd.concat([df_ext_raw[['sku', 'v_s_u']], df_s_exp]).groupby('sku')['v_s_u'].sum().reset_index()
    else:
        v_shopee_map = pd.DataFrame(columns=['sku', 'v_s_u'])

    # 4. ESTOQUE FÍSICO (JACA)
    if df_fisico_raw is not None and not df_fisico_raw.empty:
        df_fisico_raw['est_f_u'] = df_fisico_raw['estoque_atual'].apply(utils.br_to_float).fillna(0)
        df_fisico_raw['c_u'] = df_fisico_raw['preco'].apply(utils.br_to_float).fillna(0)
        est_map = df_fisico_raw.groupby('sku').agg({'est_f_u': 'sum', 'c_u': 'max'}).reset_index()
    else:
        est_map = pd.DataFrame(columns=['sku', 'est_f_u', 'c_u'])

    # 5. MERGE FINAL (REGRAS DE CANAL SEPARADAS)
    # Aqui garantimos que se o merge falhar, ele não apaga os dados
    df_res = pd.merge(df_catalogo, v_full_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res = pd.merge(df_res, est_map, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    # 6. CÁLCULO DE REPOSIÇÃO (SÓ COMPRA SE FALTAR NA "CAIXINHA")
    fator = (1 + (crescimento/100))
    # Carência FULL
    v_dia_f = (df_res['v_f_u'] * fator) / 60
    nec_f = (v_dia_f * (dias_cobertura + lead_time)) - df_res['e_f_u']
    df_res['Sugerido_Full'] = nec_f.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    
    # Carência FÍSICO
    v_dia_s = (df_res['v_s_u'] * fator) / 60
    nec_s = (v_dia_s * (dias_cobertura + lead_time)) - df_res['est_f_u']
    df_res['Sugerido_Fisico'] = nec_s.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)

    # Compra Sugerida = Soma das faltas individuais
    df_res['Compra sugerida'] = df_res['Sugerido_Full'] + df_res['Sugerido_Fisico']
    df_res['Valor total da compra sugerida'] = df_res['Compra sugerida'] * df_res['c_u']
    df_res['Valor Estoque Full'] = df_res['e_f_u'] * df_res['c_u']
    df_res['Valor Estoque Fisico'] = df_res['est_f_u'] * df_res['c_u']

    # Filtros de Status
    if 'status_reposicao' in df_res.columns:
        df_res = df_res[df_res['status_reposicao'].astype(str).lower().str.strip() != 'nao_repor']
    
    # Remove KITS da lista para focar em componentes
    if not df_kits.empty:
        df_res = df_res[~df_res['sku'].isin(df_kits['sku_kit'].unique())]

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'c_u': 'Preço de custo',
        'v_f_u': 'Vendas full', 'v_s_u': 'vendas Shopee',
        'e_f_u': 'Estoque full (Un)', 'est_f_u': 'Estoque fisico (Un)'
    })