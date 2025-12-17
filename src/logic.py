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
        # Tenta ler Excel (padrão FULL) ou CSV (padrão Shopee/Bling)
        try:
            skip = 2 if tipo_arquivo == "FULL" else 0
            df = pd.read_excel(content_io, skiprows=skip)
        except:
            content_io.seek(0)
            try:
                # CSV Separado por vírgula (Shopee costuma ser assim)
                df = pd.read_csv(content_io, encoding='utf-8-sig', sep=',', quotechar='"', skiprows=0)
                if len(df.columns) <= 1: raise Exception()
            except:
                content_io.seek(0)
                # CSV Separado por ponto e vírgula
                df = pd.read_csv(content_io, encoding='latin1', sep=';', quotechar='"', skiprows=0)

        df = utils.normalize_cols(df)
        
        # Garante SKU
        if 'sku' not in df.columns:
            for c in df.columns:
                if 'sku' in c.lower() or 'codigo' in c.lower():
                    df.rename(columns={c: 'sku'}, inplace=True)
                    break
        
        # Garante colunas numéricas
        if 'vendas_qtd' not in df.columns: df['vendas_qtd'] = 0.0
        if 'estoque_atual' not in df.columns: df['estoque_atual'] = 0.0

        return df
    except Exception as e:
        st.error(f"Erro leitura {tipo_arquivo}: {e}")
        return None

def calcular_reposicao(df_full, df_fisico, df_ext, df_kits, df_catalogo, empresa, dias_horizonte, crescimento_pct, lead_time):
    # 1. Normalização de Texto
    for df in [df_full, df_fisico, df_kits, df_catalogo]:
        if 'sku' in df.columns: df['sku'] = df['sku'].apply(utils.norm_sku)
    df_kits['sku_kit'] = df_kits['sku_kit'].apply(utils.norm_sku)
    df_kits['sku_componente'] = df_kits['sku_componente'].apply(utils.norm_sku)

    # 2. Conversão Numérica e TRAVA DE NEGATIVOS
    # O utils.br_to_float já zera negativos agora
    df_full['vendas_qtd'] = df_full['vendas_qtd'].apply(utils.br_to_float)
    df_full['estoque_atual'] = df_full['estoque_atual'].apply(utils.br_to_float)
    
    if df_ext is not None and 'vendas_qtd' in df_ext.columns:
        df_ext['vendas_qtd'] = df_ext['vendas_qtd'].apply(utils.br_to_float)
    
    df_fisico['estoque_atual'] = df_fisico['estoque_atual'].apply(utils.br_to_float)
    
    # Tratamento Catálogo
    if 'custo_medio' not in df_catalogo.columns: df_catalogo['custo_medio'] = 0.0
    if 'fornecedor' not in df_catalogo.columns: df_catalogo['fornecedor'] = "GERAL"
    df_catalogo['custo_medio'] = df_catalogo['custo_medio'].apply(utils.br_to_float)
    df_catalogo = df_catalogo.drop_duplicates(subset=['sku'])
    
    # Tratamento Kits
    if 'quantidade_no_kit' not in df_kits.columns: df_kits['quantidade_no_kit'] = 1
    df_kits['quantidade_no_kit'] = df_kits['quantidade_no_kit'].apply(utils.br_to_float)

    # --- 3. CÁLCULO DE VENDAS (SEPARADO) ---
    
    # A. Full (ML)
    vendas_full = df_full.groupby('sku')['vendas_qtd'].sum().reset_index()
    vendas_full.rename(columns={'vendas_qtd': 'Vendas_Full_60d'}, inplace=True)
    
    # B. Shopee (Externo)
    if df_ext is not None and 'vendas_qtd' in df_ext.columns:
        vendas_ext = df_ext.groupby('sku')['vendas_qtd'].sum().reset_index()
        vendas_ext.rename(columns={'vendas_qtd': 'Vendas_Shopee_60d'}, inplace=True)
    else:
        vendas_ext = pd.DataFrame(columns=['sku', 'Vendas_Shopee_60d'])

    # C. EXPLOSÃO DE KITS (AQUI ESTÁ A CORREÇÃO)
    # 1. Juntamos todas as vendas diretas para saber quanto o Kit vendeu no total
    vendas_totais_sku = pd.merge(vendas_full, vendas_ext, on='sku', how='outer').fillna(0)
    vendas_totais_sku['Total_Venda_Kit'] = vendas_totais_sku['Vendas_Full_60d'] + vendas_totais_sku['Vendas_Shopee_60d']
    
    # 2. Cruzamos com a tabela de definição de kits (Pai -> Filho)
    v_kits = pd.merge(df_kits, vendas_totais_sku, left_on='sku_kit', right_on='sku', how='inner')
    
    # 3. Multiplicamos: Venda do Kit * Qtd Componente
    v_kits['qtd_comp_explodida'] = v_kits['Total_Venda_Kit'] * v_kits['quantidade_no_kit']
    
    # 4. Agrupamos pelos FILHOS (Componentes)
    vendas_indiretas = v_kits.groupby('sku_componente')['qtd_comp_explodida'].sum().reset_index().rename(columns={'sku_componente': 'sku', 'qtd_comp_explodida': 'Vendas_Via_Explosao'})

    # --- 4. CONSOLIDAÇÃO FINAL ---
    # Base: SKUs que temos no físico ou que venderam
    skus_venda = pd.concat([vendas_full['sku'], vendas_ext['sku']]).unique()
    skus_fisico = df_fisico['sku'].unique()
    todos_skus = pd.Series(list(set(skus_venda) | set(skus_fisico)), name='sku')
    
    df_res = pd.DataFrame(todos_skus)
    
    # Traz Estoques (Já travados em zero no início)
    df_res = pd.merge(df_res, df_fisico[['sku', 'estoque_atual']], on='sku', how='left').fillna(0).rename(columns={'estoque_atual': 'Estoque_Fisico'})
    
    estoque_full_agg = df_full.groupby('sku')['estoque_atual'].sum().reset_index().rename(columns={'estoque_atual': 'Estoque_Full'})
    df_res = pd.merge(df_res, estoque_full_agg, on='sku', how='left').fillna(0)

    # Traz Vendas
    df_res = pd.merge(df_res, vendas_full, on='sku', how='left').fillna(0)
    df_res = pd.merge(df_res, vendas_ext, on='sku', how='left').fillna(0)
    # Traz a Venda Explodida (Soma no componente)
    df_res = pd.merge(df_res, vendas_indiretas, on='sku', how='left').fillna(0)
    
    # Traz Preço e Fornecedor
    df_res = pd.merge(df_res, df_catalogo[['sku', 'custo_medio', 'fornecedor']], on='sku', how='left')
    df_res['custo_medio'] = df_res['custo_medio'].fillna(0.0)
    df_res['fornecedor'] = df_res['fornecedor'].fillna("GERAL")

    # --- 5. EXTERMINADOR DE KITS (O PEDIDO PRINCIPAL) ---
    # Remove qualquer SKU que seja um "Pai" na tabela de kits
    lista_kits_pais = df_kits['sku_kit'].unique()
    df_res = df_res[~df_res['sku'].isin(lista_kits_pais)]

    # --- 6. CÁLCULO DA NECESSIDADE ---
    # Venda Total = ML + Shopee + (Venda que veio do Kit)
    df_res['Vendas_Total_Global_60d'] = df_res['Vendas_Full_60d'] + df_res['Vendas_Shopee_60d'] + df_res['Vendas_Via_Explosao']
    
    df_res['Venda_Diaria'] = df_res['Vendas_Total_Global_60d'] / 60
    
    dias_totais = dias_horizonte + lead_time
    fator_crescimento = 1 + (crescimento_pct / 100.0)
    
    df_res['Necessidade_Total'] = (df_res['Venda_Diaria'] * dias_totais) * fator_crescimento
    df_res['Estoque_Total'] = df_res['Estoque_Fisico'] + df_res['Estoque_Full']
    
    # Sugestão de Compra
    df_res['Compra_Sugerida'] = (df_res['Necessidade_Total'] - df_res['Estoque_Total']).apply(lambda x: int(x) if x > 0 else 0)
    df_res['Valor_Compra'] = df_res['Compra_Sugerida'] * df_res['custo_medio']
    
    return df_res.rename(columns={'sku': 'SKU', 'custo_medio': 'Preco_Custo', 'fornecedor': 'Fornecedor'})