import pandas as pd
import numpy as np
from dataclasses import dataclass
from .utils import norm_sku, normalize_cols, exige_colunas, br_to_float, norm_header

@dataclass
class Catalogo:
    catalogo_simples: pd.DataFrame
    kits_reais: pd.DataFrame

def construir_kits_efetivo(cat: Catalogo) -> pd.DataFrame:
    kits = cat.kits_reais.copy()
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
    base = df.copy()
    base["kit_sku"] = base[sku_col].map(norm_sku)
    base["qtd"]     = base[qtd_col].astype(int)
    merged    = base.merge(kits, on="kit_sku", how="left")
    exploded = merged.dropna(subset=["component_sku"]).copy()
    exploded["qty"] = exploded["qty"].astype(int)
    exploded["quantidade_comp"] = exploded["qtd"] * exploded["qty"]
    out = exploded.groupby("component_sku", as_index=False)["quantidade_comp"].sum()
    out = out.rename(columns={"component_sku":"SKU","quantidade_comp":"Quantidade"})
    return out

def mapear_tipo(df: pd.DataFrame) -> str:
    # Normalização prévia dos headers para identificação do tipo
    cols = [str(c).lower().strip().replace(" ", "_") for c in df.columns]
    
    tem_sku_std  = any(c in {"sku","codigo","codigo_sku","codigo_(sku)"} for c in cols) or any("sku" in c for c in cols)
    
    tem_vendas60 = any("vendas" in c and "60" in c for c in cols)
    tem_qtd_livre= any(("qtde" in c) or ("quant" in c) or ("venda" in c) or ("order" in c) for c in cols)
    
    tem_estoque_full_like = any(("estoque" in c and "full" in c) for c in cols)
    
    # Detecção robusta para o arquivo de ESTOQUE FÍSICO
    # Se tiver "estoque_atual" e "preco" ou "un", é físico
    tem_estoque_atual = any(c in {"estoque_atual", "estoque_fisico"} for c in cols)
    tem_preco = any(c in {"preco","preco_compra","preco_medio","custo","custo_medio"} for c in cols)

    if tem_sku_std and (tem_vendas60 or tem_estoque_full_like): return "FULL"
    if tem_sku_std and tem_vendas60 and tem_qtd_livre: return "FULL"
    if tem_sku_std and tem_estoque_atual and tem_preco: return "FISICO"
    if tem_sku_std and tem_qtd_livre and not tem_preco: return "VENDAS"
    
    # Fallback
    return "DESCONHECIDO"

def mapear_colunas(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    df = df.copy()
    
    # --- LIMPEZA DOS CABEÇALHOS (GARANTIA DE LEITURA) ---
    # Transforma "Estoque atual" em "estoque_atual", "Código (SKU)" em "codigo_sku", etc.
    df.columns = [
        str(c).lower().strip()
        .replace(" ", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "")
        for c in df.columns
    ]
    
    # Função auxiliar para limpar números (1.000,00 -> 1000.00) dentro desta função
    def clean_num(x):
        if isinstance(x, (int, float)): return x
        if pd.isna(x) or str(x).strip() == '': return 0
        return br_to_float(x)

    # Identificação da Coluna de SKU
    col_sku = None
    possiveis_sku = ["sku", "codigo", "codigo_sku", "id"]
    for cand in possiveis_sku:
        if cand in df.columns:
            col_sku = cand
            break
    if not col_sku:
        # Tenta achar algo que contenha sku
        for c in df.columns:
            if "sku" in c:
                col_sku = c
                break
    
    if not col_sku:
        raise RuntimeError(f"Coluna de SKU não encontrada. Colunas lidas: {list(df.columns)}")
    
    df["SKU"] = df[col_sku].map(norm_sku)

    # --- MAPEAMENTO POR TIPO ---
    if tipo == "FULL":
        # Busca Vendas
        c_v = [c for c in df.columns if "vendas" in c and "60" in c]
        if not c_v: raise RuntimeError("FULL: Faltou coluna de Vendas 60d.")
        df["Vendas_Qtd_60d"] = df[c_v[0]].map(clean_num).fillna(0).astype(int)

        # Busca Estoque Full
        c_e = [c for c in df.columns if "estoque" in c and "full" in c]
        # Fallback se não achar "full" no nome mas for do tipo FULL
        if not c_e: c_e = [c for c in df.columns if "estoque" in c]
        
        if not c_e: raise RuntimeError("FULL: Faltou coluna de Estoque Full.")
        df["Estoque_Full"] = df[c_e[0]].map(clean_num).fillna(0).astype(int)

        # Busca Em Transito
        c_t = [c for c in df.columns if "transito" in c]
        df["Em_Transito"] = df[c_t[0]].map(clean_num).fillna(0).astype(int) if c_t else 0 

        return df[["SKU","Vendas_Qtd_60d","Estoque_Full","Em_Transito"]].copy()

    if tipo == "FISICO":
        # Busca Estoque Físico (Prioridade: estoque_atual > estoque_disponivel > estoque)
        col_estoque = None
        if "estoque_atual" in df.columns: col_estoque = "estoque_atual"
        elif "estoque_disponivel" in df.columns: col_estoque = "estoque_disponivel"
        else:
            c_q = [c for c in df.columns if "estoque" in c or "qtd" in c or "quant" in c]
            if c_q: col_estoque = c_q[0]

        if not col_estoque: raise RuntimeError(f"FÍSICO: Faltou coluna de Estoque. Colunas: {list(df.columns)}")
        df["Estoque_Fisico"] = df[col_estoque].map(clean_num).fillna(0).astype(int)

        # Busca Preço
        col_preco = None
        possiveis_preco = ["preco", "preco_compra", "custo", "custo_medio", "valor", "preco_unitario"]
        for cand in possiveis_preco:
            if cand in df.columns:
                col_preco = cand
                break
        if not col_preco: raise RuntimeError("FÍSICO: Faltou coluna de Preço.")
        df["Preco"] = df[col_preco].map(clean_num).fillna(0.0)
        
        return df[["SKU","Estoque_Fisico","Preco"]].copy()

    if tipo == "VENDAS":
        # Busca Quantidade
        col_qty = None
        possiveis_qty = ["quantidade", "qtd", "qtde", "vendas"]
        for cand in possiveis_qty:
            if cand in df.columns:
                col_qty = cand
                break
        if not col_qty: 
             # Tenta achar substring
             for c in df.columns:
                 if "quant" in c or "qtd" in c:
                     col_qty = c
                     break
        
        if not col_qty: raise RuntimeError("VENDAS: Faltou coluna de Quantidade.")
        df["Quantidade"] = df[col_qty].map(clean_num).fillna(0).astype(int)
        return df[["SKU","Quantidade"]].copy()

    raise RuntimeError("Tipo de arquivo desconhecido.")

def calcular(full_df, fisico_df, vendas_df, cat: Catalogo, h=60, g=0.0, LT=0):
    kits = construir_kits_efetivo(cat)
    full = full_df.copy()
    full["SKU"] = full["SKU"].map(norm_sku)
    full["Vendas_Qtd_60d"] = full["Vendas_Qtd_60d"].astype(int)
    full["Estoque_Full"]   = full["Estoque_Full"].astype(int)
    full["Em_Transito"]    = full["Em_Transito"].astype(int) 

    # --- GARANTIA: Backup do Estoque Full para explosão ---
    full["Estoque_Full_Original"] = full["Estoque_Full"].copy()
    
    shp = vendas_df.copy()
    shp["SKU"] = shp["SKU"].map(norm_sku)
    shp["Quantidade_60d"] = shp["Quantidade"].astype(int)

    ml_comp = explodir_por_kits(
        full[["SKU","Vendas_Qtd_60d"]].rename(columns={"SKU":"kit_sku","Vendas_Qtd_60d":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"ML_60d"})
    shopee_comp = explodir_por_kits(
        shp[["SKU","Quantidade_60d"]].rename(columns={"SKU":"kit_sku","Quantidade_60d":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"Shopee_60d"})

    cat_df = cat.catalogo_simples[["component_sku","fornecedor","status_reposicao"]].rename(columns={"component_sku":"SKU"})

    demanda = cat_df.merge(ml_comp, on="SKU", how="left").merge(shopee_comp, on="SKU", how="left")
    demanda[["ML_60d","Shopee_60d"]] = demanda[["ML_60d","Shopee_60d"]].fillna(0).astype(int)
    demanda["TOTAL_60d"] = np.maximum(demanda["ML_60d"] + demanda["Shopee_60d"], demanda["ML_60d"]).astype(int)
    demanda["Vendas_Total_60d"] = demanda["ML_60d"] + demanda["Shopee_60d"] 

    fis = fisico_df.copy()
    fis["SKU"] = fis["SKU"].map(norm_sku)
    fis["Estoque_Fisico"] = fis["Estoque_Fisico"].fillna(0).astype(int)
    fis["Preco"] = fis["Preco"].fillna(0.0)

    base = demanda.merge(fis, on="SKU", how="left")
    base["Estoque_Fisico"] = base["Estoque_Fisico"].fillna(0).astype(int)
    base["Preco"] = base["Preco"].fillna(0.0)
    
    # Merge com Full Info
    full_simple = full[["SKU", "Estoque_Full", "Em_Transito", "Estoque_Full_Original"]].copy()
    base = base.merge(full_simple, on="SKU", how="left", suffixes=('_base', '_full'))
    
    # Limpeza pós-merge
    base["Estoque_Full_Original"] = base["Estoque_Full_Original"].fillna(0).astype(int) 
    base["Estoque_Full"] = base["Estoque_Full"].fillna(0).astype(int) 
    base["Em_Transito"] = base["Em_Transito"].fillna(0).astype(int) 
    base = base.drop(columns=[col for col in base.columns if col.endswith('_full') or col.endswith('_base')], errors='ignore')

    fator = (1.0 + g/100.0) ** (h/30.0)
    fk = full.copy()
    fk["vendas_dia"] = fk["Vendas_Qtd_60d"] / 60.0
    fk["alvo"] = np.round(fk["vendas_dia"] * (LT + h) * fator).astype(int)
    fk["oferta"] = (full["Estoque_Full"] + full["Em_Transito"]).astype(int)
    fk["envio_desejado"] = (fk["alvo"] - fk["oferta"]).clip(lower=0).astype(int)

    necessidade = explodir_por_kits(
        fk[["SKU","envio_desejado"]].rename(columns={"SKU":"kit_sku","envio_desejado":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"Necessidade"})

    base = base.merge(necessidade, on="SKU", how="left")
    base["Necessidade"] = base["Necessidade"].fillna(0).astype(int)

    base["Demanda_dia"]  = base["TOTAL_60d"] / 60.0
    base["Reserva_30d"]  = np.round(base["Demanda_dia"] * 30).astype(int)
    base["Folga_Fisico"] = (base["Estoque_Fisico"] - base["Reserva_30d"]).clip(lower=0).astype(int)

    base["Compra_Sugerida"] = (base["Necessidade"] - base["Folga_Fisico"]).clip(lower=0).astype(int)
    base["Valor_Compra_R$"] = (base["Compra_Sugerida"].astype(float) * base["Preco"].astype(float)).round(2)
    
    # --- EXPLOSÃO INFORMATIVA DO FULL ---
    full_stock_comp = explodir_por_kits(
        full[["SKU","Estoque_Full_Original"]].rename(columns={"SKU":"kit_sku","Estoque_Full_Original":"Qtd"}),
        kits,"kit_sku","Qtd").rename(columns={"Quantidade":"Estoque_Full_Componente"})

    base = base.merge(full_stock_comp[["SKU", "Estoque_Full_Componente"]], on="SKU", how="left").fillna(0)
    base["Estoque_Full"] = base["Estoque_Full_Componente"].astype(int)
    
    df_final = base[[
        "SKU","fornecedor",
        "Vendas_Total_60d",
        "Estoque_Full", 
        "Estoque_Fisico","Preco","Compra_Sugerida","Valor_Compra_R$",
        "ML_60d","Shopee_60d","TOTAL_60d","Reserva_30d","Folga_Fisico","Necessidade", "Em_Transito"
    ]].reset_index(drop=True)

    fis_unid  = int(fis["Estoque_Fisico"].sum())
    fisico_valor = float((fis["Estoque_Fisico"] * fis["Preco"]).sum())
    
    full_stock_kit_valor = full_stock_comp.merge(fis[["SKU","Preco"]], on="SKU", how="left")
    full_stock_kit_valor["Valor"] = full_stock_kit_valor["Estoque_Full_Componente"] * full_stock_kit_valor["Preco"].fillna(0.0)
    
    full_unid  = int(full["Estoque_Full_Original"].sum()) 
    full_valor = float(full_stock_kit_valor["Valor"].sum())

    painel = {"full_unid": full_unid, "full_valor": full_valor, "fisico_unid": fis_unid, "fisico_valor": fisico_valor}
    return df_final, painel