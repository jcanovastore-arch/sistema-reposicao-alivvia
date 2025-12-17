import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

def read_file_from_storage(empresa, tipo_arquivo):
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if content is None: return None
    
    content_io = io.BytesIO(content)
    try:
        # Se for FULL, pula as 2 linhas de cabeçalho do ML
        if tipo_arquivo == "FULL":
            df = pd.read_excel(content_io, skiprows=2)
        elif tipo_arquivo == "FISICO":
            # Seus arquivos de estoque são CSV com vírgula
            df = pd.read_csv(content_io, encoding='latin1', sep=',')
        else:
            # Vendas Shopee/Externas
            df = pd.read_csv(content_io, encoding='utf-8', sep=',')
            
        return utils.normalize_cols(df)
    except Exception as e:
        st.error(f"Erro ao ler {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(df_full, df_fisico, df_ext, df_kits, df_catalogo, empresa):
    # Normalização
    df_full['sku'] = df_full['sku'].apply(utils.norm_sku)
    df_fisico['sku'] = df_fisico['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
    
    # Unir Vendas (Full + Shopee/Ext)
    vendas_shopee = df_ext[['sku', 'vendas_qtd']].copy() if df_ext is not None else pd.DataFrame(columns=['sku', 'vendas_qtd'])
    vendas_ml = df_full[['sku', 'vendas_qtd']].copy()
    
    vendas_totais = pd.concat([vendas_ml, vendas_shopee]).groupby('sku')['vendas_qtd'].sum().reset_index()

    # EXPLOSÃO DE KITS
    vendas_com_kits = pd.merge(df_kits, vendas_totais, left_on='sku_kit', right_on='sku', how='inner')
    vendas_com_kits['vendas_calc'] = vendas_com_kits['vendas_qtd'] * vendas_com_kits['quantidade_no_kit']
    vendas_explodidas = vendas_com_kits.groupby('sku_componente')['vendas_calc'].sum().reset_index()
    vendas_explodidas.rename(columns={'sku_componente': 'sku', 'vendas_calc': 'vendas_vinda_de_kits'}, inplace=True)

    # Base Final
    df_final = pd.merge(df_fisico[['sku', 'estoque_atual']], vendas_totais, on='sku', how='left').fillna(0)
    df_final = pd.merge(df_final, vendas_explodidas, on='sku', how='left').fillna(0)
    
    df_final['Vendas_Total_60d'] = df_final['vendas_qtd'] + df_final['vendas_vinda_de_kits']
    
    # Trazer Custos
    df_final = pd.merge(df_final, df_catalogo[['sku', 'custo_medio', 'fornecedor']], on='sku', how='left')
    
    # Cálculos
    df_final['Compra_Sugerida'] = (df_final['Vendas_Total_60d'] - df_final['estoque_atual']).clip(lower=0)
    df_final['Preco_Custo'] = df_final['custo_medio'].apply(utils.br_to_float)
    df_final['Valor_Sugerido_R$'] = df_final['Compra_Sugerida'] * df_final['Preco_Custo']
    
    return df_final.rename(columns={'sku': 'SKU', 'estoque_atual': 'Estoque_Fisico', 'fornecedor': 'Fornecedor'})