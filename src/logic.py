import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# --- FUNÇÕES DE LEITURA (CONGELADAS) ---
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

    # 2. CÁLCULO DE NECESSIDADE NO FULL (LINHA POR LINHA - SEM COMPENSAÇÃO)
    # Aqui resolvemos o problema de um anúncio com 200 não ajudar o outro zerado
    nec_reposicao_full = pd.DataFrame(columns=['sku', 'v_f_u', 'e_f_u', 'demanda_abastecimento_full'])
    
    if df_full_raw is not None and not df_full_raw.empty:
        v_col = flex_col(df_full_raw, ['venda_60', 'venda_61', 'venda_qtd', 'venda'])
        e_col = flex_col(df_full_raw, ['disponivel', 'estoque_atual', 'estoque_total', 'estoque'])
        
        if v_col and e_col:
            df_full_raw['v_un'] = df_full_raw[v_col].apply(utils.br_to_float).fillna(0)
            df_full_raw['e_un'] = df_full_raw[e_col].apply(utils.br_to_float).fillna(0)
            
            # Calcula carência de cada anúncio individualmente
            v_diaria_anuncio = (df_full_raw['v_un'] * fator) / 60
            carencia_anuncio = (v_diaria_anuncio * prazo_total) - df_full_raw['e_un']
            df_full_raw['falta_no_anuncio'] = carencia_anuncio.apply(lambda x: x if x > 0 else 0)
            
            # Explosão de Kits para Componentes (Necessidade de envio)
            df_full_kits = pd.merge(df_full_raw, df_kits, left_on='sku', right_on='sku_kit', how='left')
            # Se não é kit, trata como 1 componente dele mesmo
            df_full_kits['sku_componente'] = df_full_kits['sku_componente'].fillna(df_full_kits['sku'])
            df_full_kits['quantidade_componente'] = df_full_kits['quantidade_componente'].fillna(1)
            
            # Demanda de componentes para suprir as faltas do Full
            df_full_kits['nec_comp'] = df_full_kits['falta_no_anuncio'] * df_full_kits['quantidade_componente']
            
            # Agrupa por componente para saber o total que o Full está "pedindo" do físico
            nec_reposicao_full = df_full_kits.groupby('sku_componente').agg({
                'v_un': 'sum', # Apenas para histórico visual
                'e_un': 'sum', # Apenas para histórico visual
                'nec_comp': 'sum' # O que realmente precisa ser enviado/comprado
            }).reset_index().rename(columns={
                'sku_componente': 'sku', 'v_un': 'v_f_u', 'e_un': 'e_f_u', 'nec_comp': 'nec_full'
            })

    # 3. DEMANDA DA SHOPEE
    v_shopee_map = pd.DataFrame(columns=['sku', 'v_s_u', 'demanda_shopee'])
    if df_ext_raw is not None and not df_ext_raw.empty:
        v_col_s = flex_col(df_ext_raw, ['venda', 'qtde', 'qtd', 'quantidade'])
        if v_col_s:
            df_ext_raw['v_s_u'] = df_ext_raw[v_col_s].apply(utils.br_to_float).fillna(0)
            # Explosão de kits da Shopee para demanda de componentes
            df_s_kits = pd.merge(df_ext_raw, df_kits, left_on='sku', right_on='sku_kit', how='left')
            df_s_kits['sku_componente'] = df_s_kits['sku_componente'].fillna(df_s_kits['sku'])
            df_s_kits['quantidade_componente'] = df_s_kits['quantidade_componente'].fillna(1)
            
            # Demanda real de componentes na Shopee
            v_diaria_s = (df_s_kits['v_s_u'] * fator) / 60
            df_s_kits['dem_s'] = v_diaria_s * prazo_total
            
            v_shopee_map = df_s_kits.groupby('sku_componente').agg({
                'v_s_u': 'sum', 'dem_s': 'sum'
            }).reset_index().rename(columns={'sku_componente': 'sku'})

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

    # A COMPRA SUGERIDA: (O que falta no Full + O que a Shopee vai vender) - O que eu tenho em casa
    demanda_total_casa = df_res['nec_full'] + df_res['dem_s']
    compra = demanda_total_casa - df_res['est_f_u']
    df_res['Compra sugerida'] = compra.apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    
    # Valores financeiros
    df_res['Valor total da compra sugerida'] = df_res['Compra sugerida'] * df_res['c_u']
    df_res['Valor Estoque Full'] = df_res['e_f_u'] * df_res['c_u']
    df_res['Valor Estoque Fisico'] = df_res['est_f_u'] * df_res['c_u']

    # Filtros Finais
    st_col = flex_col(df_res, ['status_reposicao', 'status_repor'])
    if st_col:
        df_res = df_res[df_res[st_col].astype(str).lower().str.strip() != 'nao_repor']
    if not df_kits.empty:
        df_res = df_res[~df_res['sku'].isin(df_kits['sku_kit'].unique())]

    return df_res.rename(columns={
        'sku': 'SKU', 'fornecedor': 'Fornecedor', 'c_u': 'Preço de custo',
        'v_f_u': 'Vendas full', 'v_s_u': 'vendas Shopee',
        'e_f_u': 'Estoque full (Un)', 'est_f_u': 'Estoque fisico (Un)'
    })