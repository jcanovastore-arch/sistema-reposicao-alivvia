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
    try:
        if tipo_arquivo == "FULL":
            # ML Full sempre pula 2 linhas
            df = pd.read_excel(content_io, skiprows=2)
        else:
            # Tenta ler CSV com detecção de separador
            try:
                content_io.seek(0)
                # Tenta vírgula (Padrão Shopee/Bling)
                df = pd.read_csv(content_io, encoding='latin1', sep=',', quotechar='"')
                if len(df.columns) <= 1: raise Exception("Incorreto")
            except:
                content_io.seek(0)
                # Tenta ponto-e-vírgula (Padrão Excel Brasil)
                df = pd.read_csv(content_io, encoding='latin1', sep=';', quotechar='"')
        
        df = utils.normalize_cols(df)
        
        # Se mesmo assim não achar o SKU, mostra as colunas encontradas para diagnóstico
        if 'sku' not in df.columns:
            st.error(f"⚠️ Erro no arquivo {tipo_arquivo} ({empresa}). Colunas lidas: {list(df.columns)}")
            return None
            
        return df
    except Exception as e:
        st.error(f"Erro ao processar {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(df_full, df_fisico, df_ext, df_kits, df_catalogo, empresa):
    # 1. Normalização
    df_full['sku'] = df_full['sku'].apply(utils.norm_sku)
    df_fisico['sku'] = df_fisico['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
    
    # 2. Vendas
    vendas = df_full[['sku', 'vendas_qtd']].copy()
    if df_ext is not None and 'vendas_qtd' in df_ext.columns:
        v_ext = df_ext[['sku', 'vendas_qtd']].copy()
        vendas = pd.concat([vendas, v_ext])
    
    vendas_totais = vendas.groupby('sku')['vendas_qtd'].sum().reset_index()

    # 3. Explosão de Kits
    v_kits = pd.merge(df_kits, vendas_totais, left_on='sku_kit', right_on='sku', how='inner')
    v_kits['v_expl'] = v_kits['vendas_qtd'] * v_kits['quantidade_no_kit']
    v_expl_agrupada = v_kits.groupby('sku_componente')['v_expl'].sum().reset_index().rename(columns={'sku_componente': 'sku'})

    # 4. Merge Final
    df_final = pd.merge(df_fisico[['sku', 'estoque_atual']], vendas_totais, on='sku', how='left').fillna(0)
    df_final = pd.merge(df_final, v_expl_agrupada, on='sku', how='left').fillna(0)
    df_final['Vendas_Total_60d'] = df_final['vendas_qtd'] + df_final['v_expl']
    
    # Traz custo e fornecedor
    df_final = pd.merge(df_final, df_catalogo[['sku', 'custo_medio', 'fornecedor']], on='sku', how='left')
    
    df_final['Compra_Sugerida'] = (df_final['Vendas_Total_60d'] - df_final['estoque_atual']).clip(lower=0)
    df_final['Preco_Custo'] = df_final['custo_medio'].apply(utils.br_to_float)
    df_final['Valor_Sugerido_R$'] = df_final['Compra_Sugerida'] * df_final['Preco_Custo']
    
    return df_final.rename(columns={'sku': 'SKU', 'estoque_atual': 'Estoque_Fisico', 'fornecedor': 'Fornecedor'})