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
    # O PULO DO GATO: O relatório FULL tem 2 linhas de cabeçalho extra que precisam ser puladas
    skip = 2 if tipo_arquivo == "FULL" else 0
    
    try:
        try:
            df = pd.read_excel(content_io, skiprows=skip)
        except:
            content_io.seek(0)
            # Lê CSV tentando detectar o separador (Shopee usa vírgula, outros podem usar ponto e vírgula)
            df = pd.read_csv(content_io, skiprows=skip, sep=None, engine='python', encoding='utf-8-sig')
        
        # Normaliza nomes de colunas (tira acentos, espaços e põe minusculo)
        df = utils.normalize_cols(df)
        return df
    except Exception as e:
        st.error(f"Erro ao ler {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. Carregar Bases
    df_full = get_relatorio_full(empresa)      # Vem do Mercado Livre
    df_ext = get_vendas_externas(empresa)      # Vem da Shopee
    df_fisico = get_estoque_fisico(empresa)    # Vem do Jaca-Estoque
    
    # Busca Catálogo (Preços e Kits) do Session State
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat: return None
    df_catalogo = dados_cat['catalogo']
    df_kits = dados_cat['kits']

    # 2. Tratamento do Estoque Físico e Custo (Jaca - Estoque)
    # Colunas no arquivo: 'estoque_atual' e 'preco'
    df_fisico['estoque_fisico'] = df_fisico['estoque_atual'].apply(utils.br_to_float).fillna(0)
    df_fisico['custo_unit'] = df_fisico['preco'].apply(utils.br_to_float).fillna(0)
    
    estoque_real = df_fisico.groupby('codigo_sku').agg({
        'estoque_fisico': 'sum',
        'custo_unit': 'max'
    }).reset_index().rename(columns={'codigo_sku': 'sku'})

    # 3. Tratamento de Vendas Full (ML)
    # Colunas no arquivo: 'vendas_qtd_61d' e 'estoque_atual'
    df_full['vendas_full_60d'] = df_full['vendas_qtd_61d'].apply(utils.br_to_float).fillna(0)
    df_full['estoque_full'] = df_full['estoque_atual'].apply(utils.br_to_float).fillna(0)
    
    vendas_full = df_full.groupby('sku').agg({
        'vendas_full_60d': 'sum',
        'estoque_full': 'sum'
    }).reset_index()

    # 4. Tratamento de Vendas Externas (Shopee)
    # Coluna no arquivo: 'qtde_vendas'
    df_ext['vendas_shopee_60d'] = df_ext['qtde_vendas'].apply(utils.br_to_float).fillna(0)
    vendas_shopee = df_ext.groupby('sku').agg({'vendas_shopee_60d': 'sum'}).reset_index()

    # 5. MERGE FINAL (Base no Catálogo)
    df_res = df_catalogo[['sku', 'fornecedor']].copy()
    df_res['sku'] = df_res['sku'].apply(utils.norm_sku)

    df_res = pd.merge(df_res, estoque_real, on='sku', how='left')
    df_res = pd.merge(df_res, vendas_full, on='sku', how='left')
    df_res = pd.merge(df_res, vendas_shopee, on='sku', how='left')
    
    df_res.fillna(0, inplace=True)

    # 6. Lógica de Cálculo
    df_res['Vendas_Total_60d'] = df_res['vendas_full_60d'] + df_res['vendas_shopee_60d']
    # Aplicar fator de crescimento se houver
    venda_ajustada = df_res['Vendas_Total_60d'] * (1 + (crescimento/100))
    df_res['Venda_Diaria'] = venda_ajustada / 60
    
    # Estoque Total
    df_res['Estoque_Total'] = df_res['estoque_fisico'] + df_res['estoque_full']
    
    # Sugestão de Compra
    # Fórmula: (Venda Diária * (Dias Cobertura + Lead Time)) - Estoque Total
    df_res['Compra_Sugerida'] = (df_res['Venda_Diaria'] * (dias_cobertura + lead_time)) - df_res['Estoque_Total']
    df_res['Compra_Sugerida'] = df_res['Compra_Sugerida'].apply(lambda x: int(np.ceil(x)) if x > 0 else 0)
    
    # Valor Total da Compra
    df_res['Valor_Compra'] = df_res['Compra_Sugerida'] * df_res['custo_unit']

    # Renomear para o padrão da UI (Interface)
    df_res.rename(columns={
        'sku': 'SKU',
        'fornecedor': 'Fornecedor',
        'estoque_fisico': 'Estoque_Fisico',
        'estoque_full': 'Estoque_Full',
        'vendas_full_60d': 'Vendas_Full_60d',
        'vendas_shopee_60d': 'Vendas_Shopee_60d',
        'custo_unit': 'Preco_Custo'
    }, inplace=True)

    return df_res