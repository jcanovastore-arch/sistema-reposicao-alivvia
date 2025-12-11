import pandas as pd
import numpy as np
import unicodedata
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

def gerar_chave_busca(text):
    """Gera uma chave limpa (slug) para identificar a coluna, independente da formatação original"""
    if not isinstance(text, str): return str(text)
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = text.lower().strip()
    # Remove caracteres especiais comuns
    text = text.replace(' ', '_').replace('.', '').replace('(', '').replace(')', '').replace('-', '_')
    return text

def mapear_tipo(df: pd.DataFrame) -> str:
    # Cria mapa {chave_limpa: nome_original}
    col_map = {gerar_chave_busca(c): c for c in df.columns}
    keys = col_map.keys()
    
    # Assinaturas
    has_sku = any(k in ['sku', 'codigo', 'codigo_sku', 'id'] for k in keys)
    has_vendas = any('vendas' in k and '60' in k for k in keys)
    
    # Estoque Físico: estoque_atual, estoque_fisico, saldo...
    has_estoque_fis = any(k in ['estoque_atual', 'estoque_fisico', 'saldo_atual'] for k in keys)
    
    if has_sku and has_vendas: return "FULL"
    if has_sku and has_estoque_fis: return "FISICO"
    
    if has_sku and any(('qtd' in k or 'quant' in k) for k in keys) and not any('estoque' in k for k in keys):
        return "VENDAS"

    # Fallback genérico para Físico se tiver a palavra estoque
    if has_sku and any('estoque' in k for k in keys):
        return "FISICO"

    return "DESCONHECIDO"

def mapear_colunas(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    df = df.copy()
    
    # --- MAPEAMENTO INTELIGENTE ---
    # 1. Cria um dicionário que liga o nome "limpo" ao nome REAL da coluna no DataFrame
    # Ex: { 'codigo_sku': 'Código (SKU)', 'estoque_atual': 'Estoque atual' } 
    # OU se já estiver limpo: { 'codigo_sku': 'codigo_sku' }
    
    col_map = {gerar_chave_busca(c): c for c in df.columns}
    
    def get_real_col(candidates):
        """Retorna o nome real da coluna com base numa lista de candidatos limpos"""
        for cand in candidates:
            if cand in col_map:
                return col_map[cand]
        # Tenta busca parcial se exato falhar
        for cand in candidates:
            for k in col_map:
                if cand in k:
                    return col_map[k]
        return None

    def clean_num(x):
        if isinstance(x, (int, float)): return x
        s = str(x).strip()
        if not s: return 0
        s = s.replace('.', '').replace(',', '.')
        try: return float(s)
        except: return 0

    # Busca SKU
    real_col_sku = get_real_col(['codigo_sku', 'sku', 'codigo', 'id'])
    
    if not real_col_sku:
        # Cria dataframe vazio seguro para não crashar
        return pd.DataFrame(columns=["SKU"])

    df["SKU"] = df[real_col_sku].map(norm_sku)

    if tipo == "FISICO":
        # Procura por estoque_atual (prioridade) ou estoque_disponivel
        real_col_est = get_real_col(['estoque_atual', 'estoque_disponivel', 'saldo', 'estoque'])
        real_col_prc = get_real_col(['preco', 'custo', 'valor'])

        if real_col_est:
            df["Estoque_Fisico"] = df[real_col_est].map(clean_num).fillna(0).astype(int)
        else:
            raise RuntimeError(f"Erro Estoque: Não achei coluna de estoque. Colunas: {list(df.columns)}")
            
        df["Preco"] = df[real_col_prc].map(clean_num).fillna(0.0) if real_col_prc else 0.0
        
        # Retorna SEM somar, apenas remove duplicatas de SKU se houver
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Estoque_Fisico", "Preco"]]

    if tipo == "FULL":
        # Busca colunas usando chaves limpas
        # Vendas 60d
        real_vendas = get_real_col(['vendas_qtd_60d', 'vendas_60d', 'vendas'])
        
        # Estoque Full
        # Tenta achar algo que tenha 'estoque' E 'full' no nome limpo
        real_full = None
        for k_limpa, v_real in col_map.items():
            if 'estoque' in k_limpa and 'full' in k_limpa:
                real_full = v_real
                break
        if not real_full: real_full = get_real_col(['estoque_full', 'estoque'])
        
        real_transito = get_real_col(['em_transito', 'transito'])

        df["Vendas_Qtd_60d"] = df[real_vendas].map(clean_num).fillna(0).astype(int) if real_vendas else 0
        df["Estoque_Full"] = df[real_full].map(clean_num).fillna(0).astype(int) if real_full else 0
        df["Em_Transito"] = df[real_transito].map(clean_num).fillna(0).astype(int) if real_transito else 0
        
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Vendas_Qtd_60d", "Estoque_Full", "Em_Transito"]]

    if tipo == "VENDAS":
        real_qty = get_real_col(['quantidade', 'qtd', 'quant', 'qtde'])
        df["Quantidade"] = df[real_qty].map(clean_num).fillna(0).astype(int) if real_qty else 0
        return df.drop_duplicates(subset=["SKU"])[["SKU", "Quantidade"]]

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
    
    # Merge direto (Left Join mantém a base de componentes)
    base = base.merge(fis, on="SKU", how="left")
    base["Estoque_Fisico"] = base["Estoque_Fisico"].fillna(0).astype(int)
    base["Preco"] = base["Preco"].fillna(0.0)

    # 3. Merge Full Info
    full_info = full[["SKU", "Estoque_Full", "Em_Transito", "Estoque_Full_Original"]].copy()
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