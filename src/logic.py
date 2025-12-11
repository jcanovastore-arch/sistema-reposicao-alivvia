import pandas as pd
import numpy as np
from dataclasses import dataclass
from .utils import norm_sku, br_to_float

@dataclass
class Catalogo:
    catalogo_simples: pd.DataFrame
    kits_reais: pd.DataFrame

def construir_kits_efetivo(cat: Catalogo) -> pd.DataFrame:
    kits = cat.kits_reais.copy()
    if cat.catalogo_simples is not None and not cat.catalogo_simples.empty:
        comps_validos = set(cat.catalogo_simples["component_sku"].unique())
        kits = kits[kits["component_sku"].isin(comps_validos)].copy()
        kits_existentes = set(kits["kit_sku"].unique())
        auto_kits = []
        for s in comps_validos:
            s_norm = norm_sku(s)
            if s_norm and s_norm not in kits_existentes:
                auto_kits.append({"kit_sku": s_norm, "component_sku": s_norm, "qty": 1})
        if auto_kits:
            kits = pd.concat([kits, pd.DataFrame(auto_kits)], ignore_index=True)
            
    return kits.drop_duplicates(subset=["kit_sku", "component_sku"])

def explodir_por_kits(df: pd.DataFrame, kits: pd.DataFrame, col_sku_in: str, col_qtd_in: str) -> pd.DataFrame:
    if df.empty: return pd.DataFrame(columns=["SKU", "Quantidade"])
    temp = df.copy()
    temp["kit_sku"] = temp[col_sku_in].map(norm_sku)
    temp["qtd_in"] = temp[col_qtd_in].fillna(0).astype(int)
    merged = temp.merge(kits, on="kit_sku", how="left")
    validos = merged.dropna(subset=["component_sku"]).copy()
    if validos.empty: return pd.DataFrame(columns=["SKU", "Quantidade"])
    validos["qtd_final"] = validos["qtd_in"] * validos["qty"]
    grouped = validos.groupby("component_sku", as_index=False)["qtd_final"].sum()
    return grouped.rename(columns={"component_sku": "SKU", "qtd_final": "Quantidade"})

def mapear_colunas(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    df = df.copy()
    cols = list(df.columns)
    
    def find_col(keywords):
        for c in cols:
            if all(k in c for k in keywords): return c
        return None
    
    col_sku = find_col(["sku"]) or find_col(["codigo"])
    if not col_sku: return pd.DataFrame(columns=["SKU"])
    df["SKU"] = df[col_sku].map(norm_sku)
    
    def safe_num(x): return br_to_float(x) if x else 0

    if tipo == "FISICO":
        col_est = find_col(["estoque", "atual"]) 
        if not col_est: col_est = find_col(["estoque", "disponivel"])
        if not col_est: col_est = find_col(["saldo"])
        col_prc = find_col(["preco"]) or find_col(["custo"])
        
        if col_est:
            df["Estoque_Fisico"] = df[col_est].apply(safe_num).fillna(0).astype(int)
        else:
            df["Estoque_Fisico"] = 0
            
        df["Preco"] = df[col_prc].apply(safe_num).fillna(0.0) if col_prc else 0.0
        
        # === CORREÇÃO CRÍTICA DO ESTOQUE FÍSICO ===
        # Se houver linhas duplicadas (SKU), pegue o MÁXIMO (mais seguro)
        df_final = df.groupby("SKU", as_index=False).agg({
            "Estoque_Fisico": "max",
            "Preco": "max"
        })
        return df_final[["SKU", "Estoque_Fisico", "Preco"]]

    elif tipo == "FULL":
        col_vendas = find_col(["vendas", "60"])
        col_full = find_col(["estoque", "full"]) or find_col(["estoque"])
        col_trans = find_col(["transito"])
        
        df["Vendas_Qtd_60d"] = df[col_vendas].apply(safe_num).fillna(0).astype(int) if col_vendas else 0
        df["Estoque_Full"] = df[col_full].apply(safe_num).fillna(0).astype(int) if col_full else 0
        df["Em_Transito"] = df[col_trans].apply(safe_num).fillna(0).astype(int) if col_trans else 0
        
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]]

    elif tipo == "VENDAS":
        col_qty = find_col(["quant"]) or find_col(["qtd"])
        df["Quantidade"] = df[col_qty].apply(safe_num).fillna(0).astype(int) if col_qty else 0
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Quantidade"]]

    return pd.DataFrame()

def calcular(full_df, fisico_df, vendas_df, cat: Catalogo, h=60, g=0.0, LT=0):
    # 1. Preparação
    kits = construir_kits_efetivo(cat)
    for c in ["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]:
        if c not in full_df.columns: full_df[c] = 0
    for c in ["SKU", "Estoque_Fisico", "Preco"]:
        if c not in fisico_df.columns: fisico_df[c] = 0
    for c in ["SKU", "Quantidade"]:
        if c not in vendas_df.columns: vendas_df[c] = 0
        
    full = full_df.copy(); full["SKU"] = full["SKU"].map(norm_sku)
    fis = fisico_df.copy(); fis["SKU"] = fis["SKU"].map(norm_sku)
    shp = vendas_df.copy(); shp["SKU"] = shp["SKU"].map(norm_sku)
    
    # 2. Explosão Vendas
    ml_comp = explodir_por_kits(full, kits, "SKU", "Vendas_Qtd_60d").rename(columns={"Quantidade": "ML_60d"})
    shp_comp = explodir_por_kits(shp, kits, "SKU", "Quantidade").rename(columns={"Quantidade": "Shopee_60d"})
    
    # 3. Base Mestra
    base = cat.catalogo_simples[["component_sku", "fornecedor"]].rename(columns={"component_sku": "SKU"}).drop_duplicates()
    base = base.merge(ml_comp, on="SKU", how="left").merge(shp_comp, on="SKU", how="left").fillna(0)
    base["TOTAL_60d"] = np.maximum(base["ML_60d"] + base["Shopee_60d"], base["ML_60d"]).astype(int)
    base["Vendas_Total_60d"] = base["TOTAL_60d"]
    
    # 4. Merge Estoque Físico
    base = base.merge(fis, on="SKU", how="left")
    base["Estoque_Fisico"] = base["Estoque_Fisico"].fillna(0).astype(int)
    base["Preco"] = base["Preco"].fillna(0.0)
    
    # 5. Cálculo Sugestão
    fator = (1.0 + g/100.0) ** (h/30.0)
    fk = full.copy()
    fk["venda_dia"] = fk["Vendas_Qtd_60d"] / 60.0
    fk["alvo"] = np.round(fk["venda_dia"] * (LT + h) * fator).astype(int)
    fk["oferta"] = (fk["Estoque_Full"] + fk["Em_Transito"]).astype(int)
    fk["envio"] = (fk["alvo"] - fk["oferta"]).clip(lower=0).astype(int)
    
    nec = explodir_por_kits(fk, kits, "SKU", "envio").rename(columns={"Quantidade": "Necessidade"})
    nec = nec.groupby("SKU", as_index=False)["Necessidade"].sum()
    
    base = base.merge(nec, on="SKU", how="left")
    base["Necessidade"] = base["Necessidade"].fillna(0).astype(int)
    
    # Reserva de 30 dias (PARA CÁLCULO DE FOLGA E ALOCAÇÃO)
    base["Reserva_30d"] = np.round((base["TOTAL_60d"]/60.0) * 30).astype(int)
    livre_virtual = (base["Estoque_Fisico"] - base["Reserva_30d"]).clip(lower=0)
    
    base["Compra_Sugerida"] = (base["Necessidade"] - livre_virtual).clip(lower=0).astype(int)
    base["Valor_Compra_R$"] = (base["Compra_Sugerida"] * base["Preco"]).round(2)
    
    # 6. Visual Full
    full_vis = explodir_por_kits(full, kits, "SKU", "Estoque_Full").rename(columns={"Quantidade": "Estoque_Full_Real"})
    full_vis = full_vis.groupby("SKU", as_index=False)["Estoque_Full_Real"].sum()
    
    base = base.merge(full_vis, on="SKU", how="left")
    base["Estoque_Full"] = base["Estoque_Full_Real"].fillna(0).astype(int)
    
    # === COLUNAS FINAIS (INCLUINDO AS NECESSÁRIAS PARA ALOCAÇÃO) ===
    cols = [
        "SKU", "fornecedor", "Vendas_Total_60d", 
        "Estoque_Full", "Estoque_Fisico", "Preco", 
        "Compra_Sugerida", "Valor_Compra_R$", 
        "Em_Transito", 
        "Reserva_30d",      # Necessário para Alocação
        "Necessidade"       # Necessário para Alocação
    ]
    return base[[c for c in cols if c in base.columns]].reset_index(drop=True), {}