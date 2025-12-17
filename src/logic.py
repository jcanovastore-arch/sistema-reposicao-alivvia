import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# --- FUNÇÕES DE SUPORTE (LEITURA CONGELADA) ---
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
            if col in ['sku', 'codigo_sku', 'sku_id', 'codigo', 'cod']:
                df.rename(columns={col: 'sku'}, inplace=True)
                break
        if 'sku' in df.columns:
            df['sku'] = df['sku'].apply(utils.norm_sku)
        return df
    except: return None

# --- LÓGICA DE EXPLOSÃO DE KITS ---
def explodir_vendas(df_vendas, df_kits, col_venda):
    if df_vendas is None or df_vendas.empty or df_kits is None or df_kits.empty:
        return pd.DataFrame(columns=['sku', col_venda])
    
    # Merge para identificar o que é KIT
    df_merge = pd.merge(df_vendas, df_kits, left_on='sku', right_on='sku_kit', how='inner')
    # Multiplica venda do KIT pela qtde do componente
    df_merge['venda_calc'] = df_merge[col_venda] * df_merge['quantidade_componente']
    
    # Agrupa por componente
    df_explodido = df_merge.groupby('sku_componente')['venda_calc'].sum().reset_index()
    df_explodido.rename(columns={'sku_componente': 'sku', 'venda_calc': col_venda}, inplace=True)
    return df_explodido

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. CARGA DE BASES
    df_full_raw = get_relatorio_full(empresa)      
    df_ext_raw = get_vendas_externas(empresa)      
    df_fisico_raw = get_estoque_fisico(empresa)    
    
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    
    df_catalogo = dados_cat['catalogo'].copy()
    df_kits = dados_cat['kits'].copy()
    
    # Padronização de SKUs
    df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)

    # 2. PROCESSAMENTO VENDAS FULL (ML) + EXPLOSÃO
    if df_full_raw is not None:
        df_full_raw['v_f_base'] = df_full_raw['vendas_qtd_61d'].apply(utils.br_to_float).fillna(0)
        # Explode kits do Full
        df_f_exp = explodir_vendas(df_full_raw[['sku', 'v_f_base']], df_kits, 'v_f_base')
        # Soma venda direta + explodida
        v_f_total = pd.concat([df_full_raw[['sku', 'v_f_base']], df_f_exp]).groupby('sku')['v_f_base'].sum().reset_index()
        # Estoque Full
        e_f_total = df_full_raw.groupby('sku')['estoque_atual'].sum().reset_index().rename(columns={'estoque_atual': 'e_f'})
        v_full_map = pd.merge(v_f_total, e_f_total, on='sku', how='outer').fillna(0)
    else:
        v_full_map = pd.DataFrame(columns=['sku', 'v_f_base', 'e_f'])

    # 3. PROCESSAMENTO VENDAS EXTERNAS (SHOPEE) + EXPLOSÃO
    if df_ext_raw is not None:
        v_col = 'qtde_vendas' if 'qtde_vendas' in df_ext_raw.columns else df_ext_raw.columns[min(2, len(df_ext_raw.columns)-1)]
        df_ext_raw['v_s_base'] = df_ext_raw[v_col].apply(utils.br_to_float).fillna(0)
        # Explode kits da Shopee
        df_s_exp = explodir_vendas(df_ext_raw[['sku', 'v_s_base']], df_kits, 'v_s_base')
        v_shopee_map = pd.concat([df_ext_raw[['sku', 'v_s_base']], df_s_exp]).groupby('sku')['v_s_base'].sum().reset_index()
    else:
        v_shopee_map = pd.DataFrame(columns=['sku', 'v_s_base'])

    # 4. ESTOQUE FÍSICO E CUSTO (JACA)
    if df_fisico_raw is not None:
        df_fisico_raw['est_f_base'] = df_fisico_raw['estoque_atual'].apply(utils.br_to_float).fillna(0)
        df_fisico_raw['custo_base'] = df_fisico_raw['preco'].apply(utils.br_to_float).fillna(0)
        est_f_map = df_fisico_raw.groupby('sku').agg({'est_f_base': 'sum', 'custo_base': 'max'}).reset_index()
    else:
        est_f_map = pd.DataFrame(columns=['sku', 'est_f_base', 'custo_base'])

    # 5. MERGE FINAL
    df_res = pd.merge(df_catalogo, v_full_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res = pd.merge(df_res, est_f_map, on='sku', how='left')
    df_res.fillna(0, inplace=True)

    # 6. CÁLCULOS POR CANAL (RESPEITANDO AS CAIXINHAS)
    fator = (1 + (crescimento/100))
    
    # Necessidade FULL
    v_diaria_full = (df_res['v_f_base'] * fator) / 60
    nec_full = (v_diaria_full * (dias_cobertura + lead_time)) - df_res['e_f']
    df_res['Sugerido_Full'] = nec_full.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    
    # Necessidade FÍSICO (Shopee)
    v_diaria_shopee = (df_res['v_s_base'] * fator) / 60
    nec_fisico = (v_diaria_shopee * (dias_cobertura + lead_time)) - df_res['est_f_base']
    df_res['Sugerido_Fisico'] = nec_fisico.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)

    # Compra Sugerida Total (Soma das carências de cada estoque)
    df_res['Compra sugerida'] = df_res['Sugerido_Full'] + df_res['Sugerido_Fisico']
    df_res['Valor total da compra sugerida'] = df_res['Compra sugerida'] * df_res['custo_base']
    
    # Valoração de Estoque
    df_res['Valor Estoque Full'] = df_res['e_f'] * df_res['custo_base']
    df_res['Valor Estoque Fisico'] = df_res['est_f_base'] * df_res['custo_base']

    # Filtro Status Reposição
    if 'status_reposicao' in df_res.columns:
        df_res = df_res[df_res['status_reposicao'].astype(str).lower().str.strip() != 'nao_repor']
    
    # Remove os KITS da lista final para focar nos componentes (opcional)
    df_res = df_res[~df_res['sku'].isin(df_kits['sku_kit'].unique())]

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'custo_base': 'Preço de custo',
        'v_f_base': 'Vendas full', 'v_s_base': 'vendas Shopee',
        'e_f': 'Estoque full (Un)', 'est_f_base': 'Estoque fisico (Un)'
    })