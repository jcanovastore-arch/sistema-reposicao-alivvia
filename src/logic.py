import pandas as pd
import streamlit as st
import io
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
        df = None
        # Pula 2 linhas para o FULL, 0 para os outros
        skip = 2 if tipo_arquivo == "FULL" else 0
        
        try:
            df = pd.read_excel(content_io, skiprows=skip)
        except:
            content_io.seek(0)
            try:
                df = pd.read_csv(content_io, encoding='utf-8-sig', sep=',', quotechar='"', skiprows=skip)
                if len(df.columns) <= 1: raise Exception()
            except:
                content_io.seek(0)
                df = pd.read_csv(content_io, encoding='latin1', sep=';', quotechar='"', skiprows=skip)

        df = utils.normalize_cols(df)
        
        # --- BLINDAGEM DE COLUNAS ---
        if 'sku' not in df.columns:
            if 'codigo_sku' in df.columns: df.rename(columns={'codigo_sku': 'sku'}, inplace=True)
            elif 'id_produto' in df.columns: df.rename(columns={'id_produto': 'sku'}, inplace=True)
        
        # Garante que as colunas numéricas existam
        if 'vendas_qtd' not in df.columns: df['vendas_qtd'] = 0.0
        if 'estoque_atual' not in df.columns: df['estoque_atual'] = 0.0

        return df
    except Exception as e:
        st.error(f"Erro leitura {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(df_full, df_fisico, df_ext, df_kits, df_catalogo, empresa):
    # 1. Normalização de Texto (SKUs)
    df_full['sku'] = df_full['sku'].apply(utils.norm_sku)
    df_fisico['sku'] = df_fisico['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
    df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)

    # 2. CONVERSÃO FORÇADA DE NÚMEROS (AQUI CONSERTA O SEU ERRO)
    # Transforma texto em número ANTES de qualquer conta
    df_full['vendas_qtd'] = df_full['vendas_qtd'].apply(utils.br_to_float)
    if df_ext is not None:
        if 'vendas_qtd' in df_ext.columns:
            df_ext['vendas_qtd'] = df_ext['vendas_qtd'].apply(utils.br_to_float)
    
    df_fisico['estoque_atual'] = df_fisico['estoque_atual'].apply(utils.br_to_float)
    
    # Garante catálogo numérico
    if 'custo_medio' not in df_catalogo.columns: df_catalogo['custo_medio'] = 0.0
    if 'fornecedor' not in df_catalogo.columns: df_catalogo['fornecedor'] = "GERAL"
    df_catalogo['custo_medio'] = df_catalogo['custo_medio'].apply(utils.br_to_float)
    
    if 'quantidade_no_kit' not in df_kits.columns: df_kits['quantidade_no_kit'] = 1
    df_kits['quantidade_no_kit'] = df_kits['quantidade_no_kit'].apply(utils.br_to_float)

    # --- LÓGICA DE NEGÓCIO ---
    
    # Vendas Totais
    vendas = df_full[['sku', 'vendas_qtd']].copy()
    if df_ext is not None and 'vendas_qtd' in df_ext.columns:
        v_ext = df_ext[['sku', 'vendas_qtd']].copy()
        vendas = pd.concat([vendas, v_ext])
    
    vendas_agrupadas = vendas.groupby('sku')['vendas_qtd'].sum().reset_index()

    # Explosão Kits
    v_com_kits = pd.merge(df_kits, vendas_agrupadas, left_on='sku_kit', right_on='sku', how='inner')
    v_com_kits['v_expl'] = v_com_kits['vendas_qtd'] * v_com_kits['quantidade_no_kit']
    v_expl_final = v_com_kits.groupby('sku_componente')['v_expl'].sum().reset_index().rename(columns={'sku_componente': 'sku'})

    # Merge Final
    df_res = pd.merge(df_fisico[['sku', 'estoque_atual']], vendas_agrupadas, on='sku', how='left').fillna(0)
    df_res = pd.merge(df_res, v_expl_final, on='sku', how='left').fillna(0)
    
    # Contas Finais (Agora segura porque tudo é float)
    df_res['Vendas_Total_60d'] = df_res['vendas_qtd'] + df_res['v_expl']
    
    # Traz Catálogo
    df_res = pd.merge(df_res, df_catalogo[['sku', 'custo_medio', 'fornecedor']], on='sku', how='left')
    df_res['custo_medio'] = df_res['custo_medio'].fillna(0.0)
    df_res['fornecedor'] = df_res['fornecedor'].fillna("GERAL")

    # Sugestão de Compra
    df_res['Compra_Sugerida'] = (df_res['Vendas_Total_60d'] - df_res['estoque_atual']).clip(lower=0)
    df_res['Valor_Sugerido_R$'] = df_res['Compra_Sugerida'] * df_res['custo_medio']
    
    return df_res.rename(columns={'sku': 'SKU', 'estoque_atual': 'Estoque_Fisico', 'fornecedor': 'Fornecedor', 'custo_medio': 'Preco_Custo'})