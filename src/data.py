import os
import io
import re
import time
import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
from typing import Optional, Tuple
import streamlit as st

# Importações internas (certifique-se que esses arquivos existem na pasta src/)
from .config import STORAGE_DIR, DEFAULT_SHEET_LINK, LOCAL_PADRAO_FILENAME
from .utils import norm_header, normalize_cols, norm_sku, exige_colunas, br_to_float
from .logic import Catalogo

def get_local_file_path(empresa: str, tipo: str) -> str:
    return os.path.join(STORAGE_DIR, f"{empresa}_{tipo}.bin")

def get_local_name_path(empresa: str, tipo: str) -> str:
    return os.path.join(STORAGE_DIR, f"{empresa}_{tipo}_name.txt")

def _requests_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.6, status_forcelist=[429,500,502,503,504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"})
    return s

def gs_export_xlsx_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"

def extract_sheet_id_from_url(url: str) -> Optional[str]:
    if not url: return None
    m = re.search(r"/d/([a-zA-Z0-9\-_]+)/", url)
    return m.group(1) if m else None

def baixar_xlsx_do_sheets(sheet_id: str) -> bytes:
    s = _requests_session()
    url = gs_export_xlsx_url(sheet_id)
    try:
        r = s.get(url, timeout=30)
        r.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"Falha ao baixar XLSX do Sheets: {e}")
    return r.content

def _carregar_padrao_de_content(content: bytes) -> Catalogo:
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception as e:
        raise RuntimeError(f"Arquivo XLSX inválido: {e}")

    def load_sheet(opts):
        for n in opts:
            if n in xls.sheet_names:
                return pd.read_excel(xls, n, dtype=str, keep_default_na=False)
        raise RuntimeError(f"Aba não encontrada. Esperado uma de {opts}.")

    df_kits = load_sheet(["KITS","KITS_REAIS","kits","kits_reais"]).copy()
    df_cat  = load_sheet(["CATALOGO_SIMPLES","CATALOGO","catalogo_simples","catalogo"]).copy()

    # KITS
    df_kits = normalize_cols(df_kits)
    possiveis_kits = {
        "kit_sku": ["kit_sku", "kit", "sku_kit"],
        "component_sku": ["component_sku","componente","sku_componente","component","sku_component"],
        "qty": ["qty","qty_por_kit","qtd_por_kit","quantidade_por_kit","qtd","quantidade"]
    }
    rename_k = {}
    for alvo, cand in possiveis_kits.items():
        for c in cand:
            if c in df_kits.columns:
                rename_k[c] = alvo; break
    df_kits = df_kits.rename(columns=rename_k)
    exige_colunas(df_kits, ["kit_sku","component_sku","qty"], "KITS")
    df_kits["kit_sku"] = df_kits["kit_sku"].map(norm_sku)
    df_kits["component_sku"] = df_kits["component_sku"].map(norm_sku)
    df_kits["qty"] = df_kits["qty"].map(br_to_float).fillna(0).astype(int)
    df_kits = df_kits[df_kits["qty"] >= 1].drop_duplicates(subset=["kit_sku","component_sku"], keep="first")

    # CATALOGO
    df_cat = normalize_cols(df_cat)
    possiveis_cat = {
        "component_sku": ["component_sku","sku","produto","item","codigo","sku_componente"],
        "fornecedor": ["fornecedor","supplier","fab","marca"],
        "status_reposicao": ["status_reposicao","status","reposicao_status"]
    }
    rename_c = {}
    for alvo, cand in possiveis_cat.items():
        for c in cand:
            if c in df_cat.columns:
                rename_c[c] = alvo; break
    df_cat = df_cat.rename(columns=rename_c)
    if "component_sku" not in df_cat.columns:
        raise ValueError("CATALOGO precisa ter a coluna 'component_sku' (ou 'sku').")
    
    mask_repor = ~df_cat["status_reposicao"].str.lower().str.contains("nao_repor", na=False)
    df_cat = df_cat[mask_repor].copy()
    df_cat = df_cat.drop_duplicates(subset=["component_sku"], keep="last").reset_index(drop=True)

    return Catalogo(catalogo_simples=df_cat, kits_reais=df_kits)

def carregar_padrao_local_ou_sheets(sheet_link: str) -> Tuple[Catalogo, str]:
    if os.path.exists(LOCAL_PADRAO_FILENAME):
        try:
            with open(LOCAL_PADRAO_FILENAME, 'rb') as f:
                content = f.read()
            return _carregar_padrao_de_content(content), "local"
        except Exception as e:
            st.warning(f"Falha local. Tentando sheets. Erro: {e}")
            time.sleep(0.5)

    try:
        sid = extract_sheet_id_from_url(sheet_link)
        content = baixar_xlsx_do_sheets(sid)
        return _carregar_padrao_de_content(content), "sheets"
    except Exception as e:
        raise RuntimeError(f"Falha Sheets: {e}")

def load_any_table_from_bytes(file_name: str, blob: bytes) -> pd.DataFrame:
    bio = io.BytesIO(blob); name = (file_name or "").lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(bio, dtype=str, keep_default_na=False, sep=None, engine="python")
        else:
            df = pd.read_excel(bio, dtype=str, keep_default_na=False)
    except Exception as e:
        raise RuntimeError(f"Erro ler arquivo '{file_name}': {e}")

    df.columns = [norm_header(c) for c in df.columns]
    tem_col_sku = any(c in df.columns for c in ["sku","codigo","codigo_sku"]) or any("sku" in c for c in df.columns)
    if (not tem_col_sku) and (len(df) > 0):
        try:
            bio.seek(0)
            if name.endswith(".csv"): df = pd.read_csv(bio, dtype=str, keep_default_na=False, header=2)
            else: df = pd.read_excel(bio, dtype=str, keep_default_na=False, header=2)
            df.columns = [norm_header(c) for c in df.columns]
        except Exception: pass

    cols = set(df.columns)
    sku_col = next((c for c in ["sku","codigo","codigo_sku"] if c in cols), None)
    if sku_col:
        df[sku_col] = df[sku_col].map(norm_sku)
        df = df[df[sku_col] != ""]
    return df.reset_index(drop=True)