import os
import io
import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
from typing import Optional, Tuple
import streamlit as st
from .config import STORAGE_DIR, DEFAULT_SHEET_LINK, LOCAL_PADRAO_FILENAME
from .utils import norm_header, norm_sku
from .logic import Catalogo

# Tenta importar tabula (para ler PDF), mas não quebra se falhar
try:
    from tabula import read_pdf
except ImportError:
    def read_pdf(*args, **kwargs): return []

# --- Funções de Caminho ---
def get_local_file_path(empresa: str, tipo: str) -> str:
    return os.path.join(STORAGE_DIR, f"{empresa}_{tipo}.bin")

def get_local_name_path(empresa: str, tipo: str) -> str:
    return os.path.join(STORAGE_DIR, f"{empresa}_{tipo}_name.txt")

# --- Sessão Robusta ---
def _requests_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

# --- Mapeamento ---
def mapear_colunas_catalogo(df: pd.DataFrame) -> pd.DataFrame:
    df_mapped = df.copy()
    df_mapped.columns = [norm_header(c) for c in df_mapped.columns]
    
    component_col = next((c for c in df_mapped.columns if 'componente' in c or 'sku_simples' in c), None)
    if not component_col:
        component_col = next((c for c in df_mapped.columns if 'sku' in c and 'kit' not in c), None)
    
    if component_col: df_mapped = df_mapped.rename(columns={component_col: "component_sku"})

    qty_col = next((c for c in df_mapped.columns if c in ['qty', 'qtd', 'quantidade', 'quant', 'qtde']), None)
    if qty_col: df_mapped = df_mapped.rename(columns={qty_col: "qty"})
    else: df_mapped["qty"] = 1

    forn_col = next((c for c in df_mapped.columns if 'fornecedor' in c or 'fabricante' in c or 'marca' in c), None)
    if forn_col: df_mapped = df_mapped.rename(columns={forn_col: "fornecedor"})
    else: df_mapped["fornecedor"] = "GERAL"

    return df_mapped

# --- Função Auxiliar Inteligente de Leitura ---
def ler_excel_ou_csv(bio_or_path):
    """Tenta ler como Excel, se falhar (não for zip), tenta CSV."""
    # Tenta ler como Excel primeiro
    try:
        if isinstance(bio_or_path, io.BytesIO): bio_or_path.seek(0)
        return pd.read_excel(bio_or_path, dtype=str)
    except Exception:
        # Se falhar (erro de zip, etc), tenta ler como CSV
        try:
            if isinstance(bio_or_path, io.BytesIO): bio_or_path.seek(0)
            return pd.read_csv(bio_or_path, sep=None, engine="python", dtype=str)
        except:
            # Última tentativa: CSV ignorando header ruim
            if isinstance(bio_or_path, io.BytesIO): bio_or_path.seek(0)
            return pd.read_csv(bio_or_path, sep=None, engine="python", dtype=str, header=2)

# --- Carregamento Padrão ---
def carregar_padrao_local_ou_sheets(url=None):
    if url is None: url = DEFAULT_SHEET_LINK
    df = None
    local_path = os.path.join(STORAGE_DIR, LOCAL_PADRAO_FILENAME)

    try:
        # 1. Tenta local
        if os.path.exists(local_path):
            df = ler_excel_ou_csv(local_path)
        
        # 2. Tenta baixar se não tiver local ou falhou
        if df is None or df.empty:
            s = _requests_session()
            response = s.get(url, timeout=45)
            if response.status_code == 200:
                bio = io.BytesIO(response.content)
                df = ler_excel_ou_csv(bio)
                # Salva localmente (o conteúdo bruto)
                with open(local_path, "wb") as f: f.write(response.content)
            else: return None, f"Erro HTTP {response.status_code}."

        if df is not None:
            df = mapear_colunas_catalogo(df)
            if "component_sku" not in df.columns: return None, "SKU Componente não encontrado."

            if 'kit_sku' in df.columns:
                kits_reais = df[df["kit_sku"].notna() & (df["kit_sku"] != "")].copy()
                catalogo_simples = df[df["kit_sku"].isna() | (df["kit_sku"] == "")].copy()
            else:
                catalogo_simples = df.copy()
                kits_reais = pd.DataFrame(columns=["kit_sku", "component_sku", "qty"])

            if "qty" in kits_reais.columns:
                kits_reais["qty"] = pd.to_numeric(kits_reais["qty"], errors='coerce').fillna(1)

            return Catalogo(catalogo_simples, kits_reais), None
    except Exception as e: return None, f"Erro Geral: {e}"
    return None, "Erro desconhecido."

# --- Leitura de PDF do Full ---
def ler_pdf_full(file_bytes):
    try:
        tabelas = read_pdf(io.BytesIO(file_bytes), pages='all', multiple_tables=True, output_format="dataframe")
        df_final = pd.DataFrame()
        
        for df_t in tabelas:
            # Tenta corrigir cabeçalho
            if len(df_t) > 1 and 'PRODUTO' not in [str(c).upper() for c in df_t.columns]:
                row0 = [str(x).upper() for x in df_t.iloc[0].values]
                if any('PRODUTO' in r for r in row0):
                    df_t.columns = df_t.iloc[0]
                    df_t = df_t[1:]
            
            df_t.columns = [norm_header(c) for c in df_t.columns]
            
            col_prod = next((c for c in df_t.columns if 'produto' in c), None)
            col_unid = next((c for c in df_t.columns if 'unidade' in c), None)

            if col_prod and col_unid:
                df_t['sku'] = df_t[col_prod].astype(str).apply(
                    lambda x: norm_sku(str(x).split('SKU:')[-1].split('\n')[0].split(' ')[0].strip()) if 'SKU:' in str(x) else ""
                )
                df_t['estoque_full'] = pd.to_numeric(df_t[col_unid], errors='coerce').fillna(0).astype(int)
                df_final = pd.concat([df_final, df_t[['