import pandas as pd
import numpy as np
from dataclasses import dataclass
from .utils import norm_sku, br_to_float

@dataclass
class Catalogo:
    catalogo_simples: pd.DataFrame
    kits_reais: pd.DataFrame

# --- FUNÇÕES DE KITS (Explosão) ---
def construir_kits_efetivo(cat: Catalogo) -> pd.DataFrame:
    kits = cat.kits_reais.copy()
    if cat.catalogo_simples is not None and not cat.catalogo_simples.empty:
        componentes_validos = set(cat.catalogo_simples["component_sku"].unique())
        kits_validos = set(kits["kit_sku"].unique())
        
        # Filtra apenas kits cujos componentes existem no catálogo
        kits = kits[kits["component_sku"].isin(componentes_validos)].copy()
        
        # Cria "Auto-Kits" para produtos unitários (SKU que é componente dele mesmo)
        alias = []
        for s in componentes_validos:
            s = norm_sku(s)
            if s and s not in kits_validos:
                alias.append((s, s, 1))
        if alias:
            kits_df_alias = pd.DataFrame(alias, columns=["kit_sku","component_sku","qty"])
            kits = pd.concat([kits, kits_df_alias], ignore_index=True)
            
    kits = kits.drop_duplicates(subset=["kit_sku","component_sku"], keep="first")
    return kits

def explodir_por_kits(df: pd.DataFrame, kits: pd.DataFrame, sku_col: str, qtd_col: str) -> pd.DataFrame:
    """Explode vendas/estoque de Kits para os seus Componentes"""
    if df.empty: return pd.DataFrame(columns=["SKU", "Quantidade"])
    base = df.copy()
    base["kit_sku"] = base[sku_col].map(norm_sku)
    base["qtd"]     = base[qtd_col].fillna(0).astype(int)
    
    # Merge com a tabela de receitas (kits)
    merged = base.merge(kits, on="kit_sku", how="left")
    
    # Remove o que não explodiu (segurança)
    exploded = merged.dropna(subset=["component_sku"]).copy()
    if exploded.empty: return pd.DataFrame(columns=["SKU", "Quantidade"])

    exploded["qty"] = exploded["qty"].astype(int)
    exploded["quantidade_comp"] = exploded["qtd"] * exploded["qty"]
    
    # Agrupa por Componente e Soma
    out = exploded.groupby("component_sku", as_index=False)["quantidade_comp"].sum()
    out = out.rename(columns={"component_sku":"SKU","quantidade_comp":"Quantidade"})
    return out

# --- MAPEAMENTO (Adaptado para data.py que já limpa colunas) ---

def mapear_colunas(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    df = df.copy()
    cols = df.columns # As colunas já vêm limpas do data.py (ex: estoque_atual)

    # Função auxiliar para encontrar coluna por palavra-chave parcial
    def get_col(keywords):
        for c in cols:
            if all(k in c for k in keywords):
                return c
        return None

    def clean_num(x):
        return br_to_float(x) if x else 0

    # Identifica SKU (data.py limpa para codigo_sku ou sku)
    col_sku = get_col(['sku']) 
    if not col_sku: col_sku = get_col(['codigo'])
    
    if not col_sku: return pd.DataFrame(columns=["SKU"]) 
    df["SKU"] = df[col_sku].map(norm_sku)

    if tipo == "FISICO":
        # Procura 'estoque_atual' (que era 'Estoque atual' antes do data.py limpar)
        col_est = get_col(['estoque', 'atual'])
        if not col_est: col_est = get_col(['estoque', 'disponivel'])
        if not col_est: col_est = get_col(['saldo']) # Fallback
        
        col_prc = get_col(['preco'])
        if not col_prc: col_prc = get_col(['custo'])

        if col_est:
            df["Estoque_Fisico"] = df[col_est].apply(br_to_float).fillna(0).astype(int)
        else:
            df["Estoque_Fisico"] = 0
            
        df["Preco"] = df[col_prc].apply(br_to_float).fillna(0.0) if col_prc else 0.0
        
        # Retorna SEM somar e SEM modificar o valor lido
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Estoque_Fisico", "Preco"]]

    elif tipo == "FULL":
        col_vendas = get_col(['vendas', '60'])
        col_full = get_col(['estoque', 'full'])
        if not col_full: col_full = get_col(['estoque']) # Cuidado para não pegar atual
        col_trans = get_col(['transito'])

        df["Vendas_Qtd_60d"] = df[col_vendas].apply(br_to_float).fillna(0).astype(int) if col_vendas else 0
        df["Estoque_Full"] = df[col_full].apply(br_to_float).fillna(0).astype(int) if col_full else 0
        df["Em_Transito"] = df[col_trans].apply(br_to_float).fillna(0).astype(int) if col_trans else 0
        
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]]

    elif tipo == "VENDAS":
        col_qty = get_col(['quant']) or get_col(['qtd'])
        df["Quantidade"] = df[col_qty].apply(br_to_float).fillna(0).astype(int) if col_qty else 0
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Quantidade"]]
    
    return pd.DataFrame()

def calcular(full_df, fisico_df, vendas_df, cat: Catalogo, h=60, g=0.0, LT=0):
    # 1. Prepara Kits
    kits = construir_kits_efetivo(cat)
    
    # 2. Garante colunas mínimas (Blindagem)
    for c in ["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]:
        if c not in full_df.columns: full_df[c] = 0
    for c in ["SKU", "Estoque_Fisico", "Preco"]:
        if c not in fisico_df.columns: fisico_df[c] = 0
    for c in ["SKU", "Quantidade"]:
        if c not in vendas_df.columns: vendas_df[c] = 0

    # 3. Normalização de SKUs
    full = full_df.copy(); full["SKU"] = full["SKU"].map(norm_sku)
    fis = fisico_df.copy(); fis["SKU"] = fis["SKU"].map(norm_sku)
    shp = vendas_df.copy(); shp["SKU"] = shp["SKU"].map(norm_sku)

    # 4. EXPLOSÃO DE DEMANDA (Vendas Kits -> Demanda Componentes)
    ml_comp = explodir_por_kits(full.rename(columns={"Vendas_Qtd_60d":"Qtd"}), kits, "SKU", "Qtd").rename(columns={"Quantidade":"ML_60d"})
    shopee_comp = explodir_por_kits(shp.rename(columns={"Quantidade":"Qtd"}), kits, "SKU", "Qtd").rename(columns={"Quantidade":"Shopee_60d"})

    # 5. BASE PRINCIPAL (Do Catálogo)
    base = cat.catalogo_simples[["component_sku","fornecedor"]].rename(columns={"component_sku":"SKU"}).drop_duplicates()
    
    # Junta as demandas
    base = base.merge(ml_comp, on="SKU", how="left").merge(shopee_comp, on="SKU", how="left").fillna(0)
    base["TOTAL_60d"] = np.maximum(base["ML_60d"] + base["Shopee_60d"], base["ML_60d"]).astype(int)
    base["Vendas_Total_60d"] = base["ML_60d"] + base["Shopee_60d"]

    # 6. MERGE ESTOQUE FÍSICO (Valor Puro)
    # Aqui o valor 949 do arquivo vai entrar direto, sem conta
    base = base.merge(fis, on="SKU", how="left")
    base["Estoque_Fisico"] = base["Estoque_Fisico"].fillna(0).astype(int)
    base["Preco"] = base["Preco"].fillna(0.0)

    # 7. CÁLCULO DE NECESSIDADE DE ENVIO (Nível Kit -> Explode para Componente)
    # Full e Trânsito são dados dos Kits (Arquivo Full)
    fator = (1.0 + g/100.0) ** (h/30.0)
    fk = full.copy()
    fk["vendas_dia"] = fk["Vendas_Qtd_60d"] / 60.0
    fk["alvo"] = np.round(fk["vendas_dia"] * (LT + h) * fator).astype(int)
    fk["oferta"] = (fk["Estoque_Full"] + fk["Em_Transito"]).astype(int)
    fk["envio_desejado"] = (fk["alvo"] - fk["oferta"]).clip(lower=0).astype(int)

    # Explode necessidade
    necessidade = explodir_por_kits(fk.rename(columns={"envio_desejado":"Qtd"}), kits, "SKU", "Qtd").rename(columns={"Quantidade":"Necessidade"})
    # Agrupa porque componentes podem vir de vários kits
    necessidade = necessidade.groupby("SKU", as_index=False)["Necessidade"].sum()

    base = base.merge(necessidade, on="SKU", how="left")
    base["Necessidade"] = base["Necessidade"].fillna(0).astype(int)

    # 8. CÁLCULO DE COMPRA
    base["Demanda_dia"]  = base["TOTAL_60d"] / 60.0
    base["Reserva_30d"]  = np.round(base["Demanda_dia"] * 30).astype(int)
    
    # Aqui calculamos a folga apenas matematicamente, não mostramos na coluna 'Estoque_Fisico'
    livre_virtual = (base["Estoque_Fisico"] - base["Reserva_30d"]).clip(lower=0)
    
    base["Compra_Sugerida"] = (base["Necessidade"] - livre_virtual).clip(lower=0).astype(int)
    base["Valor_Compra_R$"] = (base["Compra_Sugerida"] * base["Preco"]).round(2)
    
    # 9. VISUAL: ESTOQUE FULL EXPLODIDO
    # Queremos mostrar quanto de "Full" tem para aquele componente
    full_vis = explodir_por_kits(full.rename(columns={"Estoque_Full":"Qtd"}), kits, "SKU", "Qtd").rename(columns={"Quantidade":"Estoque_Full_Real"})
    full_vis = full_vis.groupby("SKU", as_index=False)["Estoque_Full_Real"].sum()
    
    base = base.merge(full_vis, on="SKU", how="left")
    base["Estoque_Full"] = base["Estoque_Full_Real"].fillna(0).astype(int)
    
    # Traz Transito também explodido (opcional, mas bom ter)
    trans_vis = explodir_por_kits(full.rename(columns={"Em_Transito":"Qtd"}), kits, "SKU", "Qtd").rename(columns={"Quantidade":"Em_Transito_Real"})
    trans_vis = trans_vis.groupby("SKU", as_index=False)["Em_Transito_Real"].sum()
    base = base.merge(trans_vis, on="SKU", how="left")
    base["Em_Transito"] = base["Em_Transito_Real"].fillna(0).astype(int)

    cols = ["SKU","fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco","Compra_Sugerida","Valor_Compra_R$", "Em_Transito"]
    return base[[c for c in cols if c in base.columns]].reset_index(drop=True), {}