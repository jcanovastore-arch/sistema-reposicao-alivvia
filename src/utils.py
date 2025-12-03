import pandas as pd
import numpy as np
from unidecode import unidecode
import streamlit as st

def norm_header(s: str) -> str:
    s = (s or "").strip()
    s = unidecode(s).lower()
    for ch in [" ", "-", "(", ")", "/", "\\", "[", "]", ".", ",", ";", ":"]:
        s = s.replace(ch, "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [norm_header(c) for c in df.columns]
    return df

def br_to_float(x):
    if pd.isna(x): return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)): return float(x)
    s = str(x).strip()
    if s == "": return np.nan
    s = s.replace("\u00a0", " ").replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try: return float(s)
    except: return np.nan

def norm_sku(x: str) -> str:
    if pd.isna(x): return ""
    return unidecode(str(x)).strip().upper()

def exige_colunas(df: pd.DataFrame, obrig: list, nome: str):
    faltam = [c for c in obrig if c not in df.columns]
    if faltam:
        raise ValueError(f"Colunas obrigatórias ausentes em {nome}: {faltam}\nColunas lidas: {list(df.columns)}")

def enforce_numeric_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["Preco", "Valor_Compra_R$", "Preco_Custo", "Valor_Sugerido_R$", "Valor_Ajustado_R$"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').round(2).astype(float)
    for col in ["Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Compra_Sugerida", "Qtd_Sugerida", "Qtd_Ajustada", "Em_Transito"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    return df

# Formatadores para exibição
def format_br_float(x):
    if pd.isna(x): return '-'
    return f"{x:,.2f}".replace('.', 'TEMP').replace(',', '.').replace('TEMP', ',')

def format_br_currency(x):
    if pd.isna(x): return '-'
    return f"R$ {format_br_float(x)}"

def format_br_int(x):
    if pd.isna(x): return '-'
    return f"{x:,.0f}".replace('.', 'TEMP').replace(',', '.').replace('TEMP', ',')

def style_df_compra(df: pd.DataFrame):
    format_mapping = {
        'Estoque_Fisico': lambda x: format_br_int(x),
        'Compra_Sugerida': lambda x: format_br_int(x),
        'Vendas_Total_60d': lambda x: format_br_int(x),
        'Estoque_Full': lambda x: format_br_int(x),
        'Em_Transito': lambda x: format_br_int(x),
        'Preco': lambda x: format_br_currency(x),
        'Valor_Compra_R$': lambda x: format_br_currency(x),
        'Qtd_Ajustada': lambda x: format_br_int(x),
        'Preco_Custo': lambda x: format_br_currency(x),
        'Valor_Ajustado_R$': lambda x: format_br_currency(x),
        'Valor_Sugerido_R$': lambda x: format_br_currency(x),
    }
    styler = df.style.format({c: fmt for c, fmt in format_mapping.items() if c in df.columns})
    
    def highlight_compra(s):
        is_compra = s.name in ['Compra_Sugerida', 'Qtd_Ajustada']
        s_numeric = pd.to_numeric(s, errors='coerce').fillna(0)
        if is_compra:
            return ['background-color: #A93226; color: white' if v > 0 else '' for v in s_numeric]
        return ['' for _ in s]

    if 'Compra_Sugerida' in df.columns:
        styler = styler.apply(highlight_compra, axis=0, subset=['Compra_Sugerida'])
    if 'Qtd_Ajustada' in df.columns:
        styler = styler.apply(highlight_compra, axis=0, subset=['Qtd_Ajustada'])
    return styler