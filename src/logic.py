import pandas as pd
import numpy as np
import io
from unidecode import unidecode
from dataclasses import dataclass

# --- Classes Auxiliares ---
@dataclass
class Catalogo:
    catalogo_simples: pd.DataFrame
    kits_reais: pd.DataFrame

# --- Funções de Tratamento de Texto ---
def norm_header(s):
    s = str(s).strip().lower()
    s = unidecode(s)
    for ch in [" ", "(", ")", ".", "-", "/"]: s = s.replace(ch, "_")
    return s

def norm_sku(x):
    if pd.isna(x): return ""
    return str(x).strip().upper()

def br_to_float(x):
    if pd.isna(x): return 0.0
    if isinstance(x, (int, float)): return float(x)
    s = str(x).strip().replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try: return float(s)
    except: return 0.0

# --- Leitura Inteligente (Ignora linhas de metadados) ---
def smart_read_excel_csv(file_bytes):
    try:
        # Tenta ler primeiras linhas para achar cabeçalho
        try: df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None, nrows=20)
        except: df_raw = pd.read_csv(io.BytesIO(file_bytes), header=None, nrows=20, sep=None, engine='python')
        
        header_idx = 0
        keywords = ["sku", "codigo", "produto", "anuncio"]
        for idx, row in df_raw.iterrows():
            txt = " ".join([str(x).lower() for x in row.values])
            if any(k in txt for k in keywords):
                header_idx = idx; break
        
        # Lê definitivo
        try: df = pd.read_excel(io.BytesIO(file_bytes), header=header_idx)
        except: df = pd.read_csv(io.BytesIO(file_bytes), header=header_idx, sep=None, engine='python')
        return df
    except: return pd.DataFrame()

def mapear_colunas(df, tipo):
    df.columns = [norm_header(c) for c in df.columns]
    cols = df.columns
    rename = {}
    
    if tipo == "FULL":
        if "sku" in cols: rename["sku"] = "SKU"
        elif "codigo_sku" in cols: rename["codigo_sku"] = "SKU"
        
        v = next((c for c in cols if "vendas_qtd" in c), None)
        if v: rename[v] = "Vendas_Full"
        
        e = next((c for c in cols if "estoque_atual" in c), None)
        if e: rename[e] = "Estoque_Full"
        
    elif tipo == "EXT":
        if "sku" in cols: rename["sku"] = "SKU"
        q = next((c for c in cols if "unidades" in c or "qtd" in c or "quantidade" in c), None)
        if q: rename[q] = "Vendas_Ext"
        
    elif tipo == "FISICO":
        s = next((c for c in cols if "codigo" in c and "sku" in c), None)
        if not s: s = next((c for c in cols if "sku" in c), None)
        if s: rename[s] = "SKU"
        
        e = next((c for c in cols if "estoque_disponivel" in c), None)
        if not e: e = next((c for c in cols if "estoque_atual" in c), None)
        if e: rename[e] = "Estoque_Fisico"
        
        p = next((c for c in cols if "preco" in c), None)
        if p: rename[p] = "Preco"
        
    df = df.rename(columns=rename)
    if "SKU" in df.columns: df["SKU"] = df["SKU"].apply(norm_sku)
    
    for c in ["Vendas_Full", "Vendas_Ext", "Estoque_Full", "Estoque_Fisico", "Preco"]:
        if c in df.columns: df[c] = df[c].apply(br_to_float)
            
    return df

# --- Cálculo de Necessidade ---
def calcular_reposicao(df_full, df_ext, df_fis, catalogo, dias, cresc, lead):
    base = df_full.copy() if not df_full.empty else pd.DataFrame(columns=["SKU"])
    if "SKU" not in base.columns: return pd.DataFrame()
    
    # Merge Vendas Externas (Shopee)
    if not df_ext.empty and "SKU" in df_ext.columns:
        ext_g = df_ext[["SKU", "Vendas_Ext"]].groupby("SKU", as_index=False).sum()
        base = base.merge(ext_g, on="SKU", how="outer").fillna(0)
    else: base["Vendas_Ext"] = 0.0
    
    # Merge Estoque Físico
    if not df_fis.empty and "SKU" in df_fis.columns:
        # Pega maior preço caso duplicado, soma estoque
        fis_g = df_fis.groupby("SKU", as_index=False).agg({"Estoque_Fisico": "sum", "Preco": "max"})
        base = base.merge(fis_g, on="SKU", how="left").fillna(0)
    else: base["Estoque_Fisico"] = 0.0; base["Preco"] = 0.0
    
    # Garante colunas numéricas
    for c in ["Vendas_Full", "Estoque_Full", "Vendas_Ext", "Estoque_Fisico", "Preco"]:
        if c not in base.columns: base[c] = 0.0
        base[c] = base[c].fillna(0)
        
    # Matemática
    base["Vendas_Total_60d"] = base["Vendas_Full"] + base["Vendas_Ext"]
    base["Media_Dia"] = (base["Vendas_Total_60d"] / 60.0) * (1 + cresc/100)
    base["Necessidade"] = base["Media_Dia"] * (dias + lead)
    base["Estoque_Total"] = base["Estoque_Full"] + base["Estoque_Fisico"]
    
    base["Sugestao"] = (base["Necessidade"] - base["Estoque_Total"]).apply(np.ceil).clip(lower=0)
    base["Custo_Sugestao"] = base["Sugestao"] * base["Preco"]
    
    return base.sort_values("Sugestao", ascending=False)