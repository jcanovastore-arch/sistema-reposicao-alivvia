import pandas as pd
import streamlit as st
import io
import numpy as np
from src import storage, utils 

# Funções de Atalho
def get_relatorio_full(empresa): return read_file_from_storage(empresa, "FULL")
def get_vendas_externas(empresa): return read_file_from_storage(empresa, "EXT")
def get_estoque_fisico(empresa): return read_file_from_storage(empresa, "FISICO")

def read_file_from_storage(empresa, tipo_arquivo):
    \"\"\"Lê arquivos do Supabase tratando erros de codificação e delimitadores.\"\"\"
    path = f"{empresa}/{tipo_arquivo}.xlsx"
    content = storage.download(path)
    if content is None: return None
    
    content_io = io.BytesIO(content)
    try:
        if tipo_arquivo == "FULL":
            # Relatório do Full do ML sempre tem 2 linhas de lixo no topo
            df = pd.read_excel(content_io, skiprows=2)
        else:
            # Tenta ler CSV (Bling e Shopee)
            try:
                content_io.seek(0)
                # utf-8-sig mata o erro do caractere "i>>?"
                df = pd.read_csv(content_io, encoding='utf-8-sig', sep=',', quotechar='"')
                if len(df.columns) <= 1: raise Exception(\"Separador incorreto\")
            except:
                content_io.seek(0)
                # Fallback para o padrão Excel/CSV nacional (Ponto e vírgula)
                df = pd.read_csv(content_io, encoding='latin1', sep=';', quotechar='"')
        
        # Aplica a normalização de colunas do utils.py
        df = utils.normalize_cols(df)
        
        # Validação final: se não achou a coluna SKU, avisa o usuário
        if 'sku' not in df.columns:
            st.error(f"⚠️ Erro no arquivo {tipo_arquivo} ({empresa}). Colunas encontradas: {list(df.columns)}")
            return None
            
        return df
    except Exception as e:
        st.error(f"Erro ao processar {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(df_full, df_fisico, df_ext, df_kits, df_catalogo, empresa):
    \"\"\"Lógica central: Soma vendas, explode kits e sugere compra.\"\"\"
    
    # 1. Padronização de SKUs para garantir que o 'ITEM-A' no estoque bata com 'item-a' nas vendas
    df_full['sku'] = df_full['sku'].apply(utils.norm_sku)
    df_fisico['sku'] = df_fisico['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)
    
    # 2. Consolidação de Vendas (ML + Shopee)
    vendas_ml = df_full[['sku', 'vendas_qtd']].copy()
    
    if df_ext is not None and 'vendas_qtd' in df_ext.columns:
        vendas_sh = df_ext[['sku', 'vendas_qtd']].copy()
        vendas_totais = pd.concat([vendas_ml, vendas_sh])
    else:
        vendas_totais = vendas_ml
        
    vendas_agrupadas = vendas_totais.groupby('sku')['vendas_qtd'].sum().reset_index()

    # 3. EXPLOSÃO DE KITS
    # Cruza vendas totais com a tabela de kits
    v_com_kits = pd.merge(df_kits, vendas_agrupadas, left_on='sku_kit', right_on='sku', how='inner')
    # Multiplica venda do kit pela quantidade de peças dentro dele
    v_com_kits['v_expl'] = v_com_kits['vendas_qtd'] * v_com_kits['quantidade_no_kit']
    # Agrupa por componente (um item pode estar em vários kits diferentes)
    v_expl_final = v_com_kits.groupby('sku_componente')['v_expl'].sum().reset_index().rename(columns={'sku_componente': 'sku'})

    # 4. MERGE FINAL (Base no estoque físico)
    df_res = pd.merge(df_fisico[['sku', 'estoque_atual']], vendas_agrupadas, on='sku', how='left').fillna(0)
    df_res = pd.merge(df_res, v_expl_final, on='sku', how='left').fillna(0)
    
    # Venda Total = Venda Direta + Venda vinda de Kits
    df_res['Vendas_Total_60d'] = df_res['vendas_qtd'] + df_res['v_expl']
    
    # Traz informações de custo e fornecedor do catálogo
    df_res = pd.merge(df_res, df_catalogo[['sku', 'custo_medio', 'fornecedor']], on='sku', how='left')
    
    # 5. CÁLCULOS DE SUGESTÃO
    df_res['Compra_Sugerida'] = (df_res['Vendas_Total_60d'] - df_res['estoque_atual']).clip(lower=0)
    df_res['Preco_Custo'] = df_res['custo_medio'].apply(utils.br_to_float)
    df_res['Valor_Sugerido_R$'] = df_res['Compra_Sugerida'] * df_res['Preco_Custo']
    
    return df_res.rename(columns={'sku': 'SKU', 'estoque_atual': 'Estoque_Fisico', 'fornecedor': 'Fornecedor'})