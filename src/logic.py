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
        componentes_validos = set(cat.catalogo_simples["component_sku"].unique())
        kits_validos = set(kits["kit_sku"].unique())
        kits = kits[kits["component_sku"].isin(componentes_validos)].copy()
        
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
    if df.empty: return pd.DataFrame(columns=["SKU", "Quantidade"])
    base = df.copy()
    base["kit_sku"] = base[sku_col].map(norm_sku)
    base["qtd"]     = base[qtd_col].fillna(0).astype(int)
    merged    = base.merge(kits, on="kit_sku", how="left")
    
    exploded = merged.dropna(subset=["component_sku"]).copy()
    if exploded.empty: return pd.DataFrame(columns=["SKU", "Quantidade"])

    exploded["qty"] = exploded["qty"].astype(int)
    exploded["quantidade_comp"] = exploded["qtd"] * exploded["qty"]
    out = exploded.groupby("component_sku", as_index=False)["quantidade_comp"].sum()
    out = out.rename(columns={"component_sku":"SKU","quantidade_comp":"Quantidade"})
    return out

def mapear_tipo(df: pd.DataFrame) -> str:
    # Verifica EXATAMENTE os nomes do seu CSV
    if "Estoque atual" in df.columns and "Código (SKU)" in df.columns:
        return "FISICO"
    
    # Verifica assinaturas aproximadas para os outros arquivos
    cols = [str(c).lower() for c in df.columns]
    if any("vendas" in c and "60" in c for c in cols): return "FULL"
    if any("quant" in c for c in cols) and not any("estoque" in c for c in cols): return "VENDAS"

    return "DESCONHECIDO"

def mapear_colunas(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    df = df.copy()
    
    # Limpeza simples de número
    def clean_num(x):
        if isinstance(x, (int, float)): return x
        s = str(x).strip()
        if not s: return 0
        s = s.replace('.', '').replace(',', '.')
        try: return float(s)
        except: return 0

    # --- MAPEAMENTO ---

    if tipo == "FISICO":
        # LEITURA EXATA DO SEU ARQUIVO
        # Se estas colunas não existirem, o erro vai dizer exatamente isso.
        
        try:
            df["SKU"] = df["Código (SKU)"].map(norm_sku)
            df["Estoque_Fisico"] = df["Estoque atual"].map(clean_num).fillna(0).astype(int)
            
            if "Preço" in df.columns:
                df["Preco"] = df["Preço"].map(clean_num).fillna(0.0)
            else:
                df["Preco"] = 0.0
                
        except KeyError as e:
            raise RuntimeError(f"Erro Crítico: O arquivo Físico NÃO tem a coluna exata: {e}. Colunas lidas: {list(df.columns)}")

        # Retorna apenas as colunas necessárias, sem agrupar
        return df[["SKU", "Estoque_Fisico", "Preco"]]

    # Para FULL e VENDAS, mantemos a busca flexível pois não tenho esses arquivos aqui para validar
    if tipo == "FULL":
        cols_lower = {c.lower(): c for c in df.columns}
        
        col_sku = next((orig for low, orig in cols_lower.items() if "sku" in low or "codigo" in low), None)
        col_vendas = next((orig for low, orig in cols_lower.items() if "vendas" in low and "60" in low), None)
        col_full = next((orig for low, orig in cols_lower.items() if "estoque" in low and "full" in low), None)
        if not col_full: col_full = next((orig for low, orig in cols_lower.items() if "estoque" in low), None)
        col_transito = next((orig for low, orig in cols_lower.items() if "transito" in low), None)

        if not col_sku: df["SKU"] = "DESCONHECIDO"
        else: df["SKU"] = df[col_sku].map(norm_sku)
            
        df["Vendas_Qtd_60d"] = df[col_vendas].map(clean_num).astype(int) if col_vendas else 0
        df["Estoque_Full"] = df[col_full].map(clean_num).astype(int) if col_full else 0
        df["Em_Transito"] = df[col_transito].map(clean_num).astype(int) if col_transito else 0
        
        return df[["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]]

    if tipo == "VENDAS":
        cols_lower = {c.lower(): c for c in df.columns}
        col_sku = next((orig for low, orig in cols_lower.items() if "sku" in low), None)
        col_qty = next((orig for low, orig in cols_lower.items() if "quant" in low or "qtd" in low), None)
        
        if not col_sku: df["SKU"] = "DESCONHECIDO"
        else: df["SKU"] = df[col_sku].map(norm_sku)
            
        df["Quantidade"] = df[col_qty].map(clean_num).astype(int) if col_qty else 0
        return df[["SKU", "Quantidade"]]

    return pd.DataFrame()

def calcular(full_df, fisico_df, vendas_df, cat: Catalogo, h=60, g=0.0, LT=0):
    kits = construir_kits_efetivo(cat)
    
    # Preenchimento de segurança
    for c in ["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]:
        if c not in full_df.columns: full_df[c] = 0
    for c in ["SKU", "Estoque_Fisico", "Preco"]:
        if c not in fisico_df.columns: fisico_df[c] = 0
    for c in ["SKU", "Quantidade"]:
        if c not in vendas_df.columns: vendas_df[c] = 0
        
    full = full_df.copy()
    full["SKU"] = full["SKU"].map(norm_sku)
    full["Estoque_Full_Original"] = full["Estoque_Full"].copy()
    
    shp = vendas_df.copy()
    shp["SKU"] = shp["SKU"].map(norm_sku)

    # 1. Demanda
    ml_comp = explodir_por_kits(
        full[["SKU","Vendas_Qtd_60d"]].rename(columns={"SKU":"kit_sku","Vendas_Qtd_60d":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"ML_60d"})
        
    shopee_comp = explodir_por_kits(
        shp[["SKU","Quantidade"]].rename(columns={"SKU":"kit_sku","Quantidade":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"Shopee_60d"})

    cat_df = cat.catalogo_simples[["component_sku","fornecedor"]].rename(columns={"component_sku":"SKU"}).drop_duplicates()
    base = cat_df.merge(ml_comp, on="SKU", how="left").merge(shopee_comp, on="SKU", how="left").fillna(0)
    base["TOTAL_60d"] = np.maximum(base["ML_60d"] + base["Shopee_60d"], base["ML_60d"]).astype(int)
    base["Vendas_Total_60d"] = base["ML_60d"] + base["Shopee_60d"]

    # 2. Merge Estoque Físico
    fis = fisico_df.copy()
    fis["SKU"] = fis["SKU"].map(norm_sku)
    
    # Remove duplicatas de SKU no físico pegando o primeiro que aparecer (evita multiplicação de linhas)
    fis = fis.drop_duplicates(subset=["SKU"])
    
    base = base.merge(fis, on="SKU", how="left")
    base["Estoque_Fisico"] = base["Estoque_Fisico"].fillna(0).astype(int)
    base["Preco"] = base["Preco"].fillna(0.0)

    # 3. Merge Full Info
    full_info = full[["SKU", "Estoque_Full", "Em_Transito", "Estoque_Full_Original"]].copy()
    # Remove duplicatas de SKU no Full
    full_info = full_info.drop_duplicates(subset=["SKU"])
    
    base = base.merge(full_info, on="SKU", how="left", suffixes=("", "_FULL_RAW"))
    for c in ["Estoque_Full", "Em_Transito", "Estoque_Full_Original"]:
        if c in base.columns: base[c] = base[c].fillna(0).astype(int)
        else: base[c] = 0

    # 4. Cálculo Logística
    fator = (1.0 + g/100.0) ** (h/30.0)
    fk = full.copy()
    fk["vendas_dia"] = fk["Vendas_Qtd_60d"] / 60.0
    fk["alvo"] = np.round(fk["vendas_dia"] * (LT + h) * fator).astype(int)
    fk["oferta"] = (fk["Estoque_Full"] + fk["Em_Transito"]).astype(int)
    fk["envio_desejado"] = (fk["alvo"] - fk["oferta"]).clip(lower=0).astype(int)

    necessidade = explodir_por_kits(
        fk[["SKU","envio_desejado"]].rename(columns={"SKU":"kit_sku","envio_desejado":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"Necessidade"})
    
    # Remove duplicatas da necessidade
    necessidade = necessidade.drop_duplicates(subset=["SKU"])

    base = base.merge(necessidade, on="SKU", how="left")
    base["Necessidade"] = base["Necessidade"].fillna(0).astype(int)

    # 5. Compra Final
    base["Demanda_dia"]  = base["TOTAL_60d"] / 60.0
    base["Reserva_30d"]  = np.round(base["Demanda_dia"] * 30).astype(int)
    base["Folga_Fisico"] = (base["Estoque_Fisico"] - base["Reserva_30d"]).clip(lower=0).astype(int)
    base["Compra_Sugerida"] = (base["Necessidade"] - base["Folga_Fisico"]).clip(lower=0).astype(int)
    base["Valor_Compra_R$"] = (base["Compra_Sugerida"] * base["Preco"]).round(2)
    
    # 6. Visual Full
    full_exploded = explodir_por_kits(
        full[["SKU","Estoque_Full_Original"]].rename(columns={"SKU":"kit_sku","Estoque_Full_Original":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"Estoque_Full_Real"})
    
    full_exploded = full_exploded.drop_duplicates(subset=["SKU"])
        
    base = base.merge(full_exploded, on="SKU", how="left")
    base["Estoque_Full"] = base["Estoque_Full_Real"].fillna(0).astype(int)

    cols_finais = [
        "SKU","fornecedor", "Vendas_Total_60d", "Estoque_Full", 
        "Estoque_Fisico", "Preco","Compra_Sugerida","Valor_Compra_R$",
        "ML_60d","Shopee_60d","TOTAL_60d","Reserva_30d","Folga_Fisico","Necessidade", "Em_Transito"
    ]
    for c in cols_finais:
        if c not in base.columns: base[c] = 0
        
    return base[cols_finais].reset_index(drop=True), {}