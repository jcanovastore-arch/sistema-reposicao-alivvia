# reposicao_app.py
# Reposição Logística — Alivvia (Modular V8.2 - COM CURVA ABC & SEGURANÇA)

import os
import shutil
import datetime as dt
import pandas as pd
import streamlit as st
import requests
import time
import io
import json
import numpy as np

# --- Importações para PDF ---
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib.utils import ImageReader

# Importações dos módulos da pasta src
from src.config import DEFAULT_SHEET_LINK, LOCAL_PADRAO_FILENAME, STORAGE_DIR
from src.utils import enforce_numeric_types, style_df_compra, norm_sku, format_br_currency, br_to_float
from src.data import (
    get_local_file_path, get_local_name_path, load_any_table_from_bytes, 
    carregar_padrao_local_ou_sheets, _carregar_padrao_de_content
)
from src.logic import Catalogo, mapear_tipo, mapear_colunas, calcular, construir_kits_efetivo, explodir_por_kits

# Importando as funções de Banco de Dados (Supabase)
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

# ===================== CONFIGURAÇÃO DA PÁGINA =====================
st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== SISTEMA DE LOGIN (V8.1) =====================
def check_password():
    """Retorna True se o usuário logou corretamente."""
    def password_entered():
        if st.session_state["password"] == st.secrets["access"]["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔒 Digite a Senha de Acesso:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 Digite a Senha de Acesso:", type="password", on_change=password_entered, key="password")
        st.error("😕 Senha incorreta.")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ===================== FUNÇÕES AUXILIARES =====================
def reset_selection():
    st.session_state.sel_A = {}
    st.session_state.sel_J = {}

def exportar_csv_generico(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=';', decimal=',').encode("utf-8-sig")

# --- NOVA FUNÇÃO V8.2: CALCULAR CURVA ABC ---
def gerar_curva_abc(df_resultado):
    """
    Recebe o DataFrame de resultado (que tem vendas e preço) e calcula a curva ABC.
    Baseado em Faturamento (Vendas 60d * Preço).
    """
    if df_resultado is None or df_resultado.empty:
        return None

    df = df_resultado.copy()
    
    # Garante numéricos
    df["Vendas_Total_60d"] = pd.to_numeric(df["Vendas_Total_60d"], errors='coerce').fillna(0)
    df["Preco"] = pd.to_numeric(df["Preco"], errors='coerce').fillna(0)
    
    # Calcula Faturamento Estimado (60 dias)
    df["Faturamento_60d"] = df["Vendas_Total_60d"] * df["Preco"]
    
    # Ordena do maior para o menor faturamento
    df = df.sort_values(by="Faturamento_60d", ascending=False).reset_index(drop=True)
    
    # Calcula Acumulado
    faturamento_total = df["Faturamento_60d"].sum()
    if faturamento_total == 0:
        df["%_Acumulado"] = 0
        df["Classe"] = "C"
    else:
        df["%_Acumulado"] = df["Faturamento_60d"].cumsum() / faturamento_total
        
        # Classificação ABC Clássica (80-15-5)
        def classificar(perc):
            if perc <= 0.80: return "A"
            elif perc <= 0.95: return "B"
            return "C"
        
        df["Classe"] = df["%_Acumulado"].apply(classificar)

    # Seleciona colunas bonitas para exportar
    cols_export = [
        "Classe", "SKU", "fornecedor", 
        "Vendas_Total_60d", "Preco", "Faturamento_60d", 
        "Estoque_Full", "Estoque_Fisico", "Compra_Sugerida"
    ]
    cols_finais = [c for c in cols_export if c in df.columns]
    
    return df[cols_finais]

def _ensure_state():
    st.session_state.setdefault("catalogo_df", None)
    st.session_state.setdefault("kits_df", None)
    st.session_state.setdefault("loaded_at", None)
    st.session_state.setdefault("alt_sheet_link", DEFAULT_SHEET_LINK)
    st.session_state.setdefault("resultado_ALIVVIA", None)
    st.session_state.setdefault("resultado_JCA", None)
    st.session_state.setdefault('sel_A', {})
    st.session_state.setdefault('sel_J', {})
    st.session_state.setdefault('current_skus_A', [])
    st.session_state.setdefault('current_skus_J', [])
    
    st.session_state.setdefault("pedido_ativo", {
        "itens": [], "fornecedor": None, "empresa": None, "obs": ""
    })

    for emp in ["ALIVVIA", "JCA"]:
        st.session_state.setdefault(emp, {})
        for file_type in ["FULL", "VENDAS", "ESTOQUE"]:
            state = st.session_state[emp].setdefault(file_type, {"name": None, "bytes": None})
            if not state["name"]:
                path_bin = get_local_file_path(emp, file_type)
                path_name = get_local_name_path(emp, file_type)
                if os.path.exists(path_bin) and os.path.exists(path_name):
                    try:
                        with open(path_bin, 'rb') as f_bin: state["bytes"] = f_bin.read()
                        with open(path_name, 'r', encoding='utf-8') as f_name: state["name"] = f_name.read().strip()
                        state['is_cached'] = True
                    except: state["name"] = None; state["bytes"] = None

_ensure_state()

# Callback de Seleção
def callback_update_selection(key_widget, key_skus, sel_dict):
    if key_widget not in st.session_state: return
    changes = st.session_state[key_widget]["edited_rows"]
    current_skus = st.session_state[key_skus]
    for idx, change in changes.items():
        if "Selecionar" in change:
            if idx < len(current_skus):
                sku_clicado = current_skus[idx]
                sel_dict[sku_clicado] = change["Selecionar"]
    time.sleep(0.01)

# Callback Editor OC
def callback_editor_oc():
    state = st.session_state.get("editor_oc_main")
    if not state: return
    lista_atual = st.session_state.pedido_ativo["itens"]
    
    deleted = state.get("deleted_rows", [])
    if deleted:
        for idx in sorted(deleted, reverse=True):
            if idx < len(lista_atual):
                lista_atual.pop(idx)
    
    edited = state.get("edited_rows", {})
    for idx_str, changes in edited.items():
        idx = int(idx_str)
        if idx < len(lista_atual):
            item = lista_atual[idx]
            if "qtd" in changes: item["qtd"] = int(changes["qtd"])
            if "valor_unit" in changes: item["valor_unit"] = float(changes["valor_unit"])
            lista_atual[idx] = item
    st.session_state.pedido_ativo["itens"] = lista_atual

# Busca Preço
def buscar_preco_custo_profundo(sku_alvo):
    sku_alvo = norm_sku(sku_alvo)
    for emp in ["ALIVVIA", "JCA"]:
        res = st.session_state.get(f"resultado_{emp}")
        if res is not None and not res.empty:
            match = res[res["SKU"] == sku_alvo]
            if not match.empty:
                p = float(match.iloc[0]["Preco"])
                if p > 0: return p
    for emp in ["ALIVVIA", "JCA"]:
        d = st.session_state.get(emp, {})
        for tipo in ["ESTOQUE", "FULL"]:
            obj = d.get(tipo)
            if obj and obj.get("bytes"):
                try:
                    df_raw = load_any_table_from_bytes(obj["name"], obj["bytes"])
                    cols_p = [c for c in df_raw.columns if "preco" in c.lower() or "custo" in c.lower()]
                    cols_s = [c for c in df_raw.columns if "sku" in c.lower() or "codigo" in c.lower()]
                    if cols_p and cols_s:
                        df_raw["SKU_NORM"] = df_raw[cols_s[0]].map(norm_sku)
                        match = df_raw[df_raw["SKU_NORM"] == sku_alvo]
                        if not match.empty:
                            val = br_to_float(match.iloc[0][cols_p[0]])
                            if val > 0: return val
                except: pass
    return 0.0

# --- PDF GENERATOR ---
def gerar_pdf_oc(oc_id: str, dados_oc: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    Story = []

    # Estilos
    style_titulo = ParagraphStyle('TituloOC', parent=styles['Heading1'], fontSize=16, alignment=TA_RIGHT, spaceAfter=20)
    style_normal = styles['Normal']
    style_bold = ParagraphStyle('Bold', parent=styles['Normal'], fontName='Helvetica-Bold')

    # CABEÇALHO
    empresa_atual = dados_oc.get('empresa', 'ALIVVIA')
    logo_path = "logo_jca.png" if empresa_atual == "JCA" else "logo_alivvia.png"

    if os.path.exists(logo_path):
        try:
            img_reader = ImageReader(logo_path)
            img_w, img_h = img_reader.getSize()
            aspect = img_h / float(img_w)
            max_h = 0.8 * inch
            max_w = 3.0 * inch
            new_w = max_h / aspect
            new_h = max_h
            if new_w > max_w:
                new_w = max_w
                new_h = max_w * aspect
            logo_img = RLImage(logo_path, width=new_w, height=new_h)
            logo_img.hAlign = 'LEFT'
        except:
            logo_img = Paragraph(f"<b>[{empresa_atual}]</b>", style_bold)
    else:
        logo_img = Paragraph(f"<b>[{empresa_atual}]</b>", style_bold)

    valor_total_br = f"R$ {dados_oc.get('valor_total', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    header_data = [
        [logo_img, Paragraph(f"<b>ORDEM DE COMPRA</b><br/><font size=12>{oc_id}</font>", style_titulo)],
        ["", ""],
        [Paragraph(f"<b>Fornecedor:</b> {dados_oc.get('fornecedor', '-')}", style_normal), 
         Paragraph(f"<b>Data:</b> {dados_oc.get('data_emissao', '-')}", style_normal)],
        [Paragraph(f"<b>Empresa:</b> {empresa_atual}", style_normal), 
         Paragraph(f"<b>Valor Total:</b> {valor_total_br}", style_normal)]
    ]

    t_header = Table(header_data, colWidths=[3.5*inch, 3.5*inch])
    t_header.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (0,0), 'LEFT'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LINEBELOW', (0,1), (-1,1), 1, colors.black),
        ('TOPPADDING', (0,2), (-1,-1), 8),
    ]))
    Story.append(t_header)
    Story.append(Spacer(1, 0.3*inch))
    
    # TABELA ITENS
    itens_df = pd.DataFrame(dados_oc['itens'])
    data = [['SKU', 'Qtd', 'Unit (R$)', 'Total (R$)', 'Qtd Conferida']]
    
    for _, row in itens_df.iterrows():
        t_item = row['qtd'] * row['valor_unit']
        c_br = f"{row['valor_unit']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        t_br = f"{t_item:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        data.append([row['sku'], str(row['qtd']), c_br, t_br, '__________'])

    table = Table(data, colWidths=[2.5*inch, 0.8*inch, 1.2*inch, 1.2*inch, 1.3*inch])
    table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (0,1), (0,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white]),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    Story.append(table)
    Story.append(Spacer(1, 0.4*inch))
    
    # CHECKLIST
    Story.append(Paragraph("<b>CHECKLIST DE RECEBIMENTO & AUDITORIA</b>", style_bold))
    Story.append(Spacer(1, 0.1*inch))
    checklist_data = [
        ["[   ] Nota Fiscal Entregue", "[   ] Volumes Íntegros (Sem avarias)"],
        ["[   ] Quantidades Conferidas", "[   ] Data de Entrega: ____/____/______"]
    ]
    t_check = Table(checklist_data, colWidths=[3.5*inch, 3.5*inch])
    t_check.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.black),
        ('CQ_PADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    Story.append(t_check)
    Story.append(Spacer(1, 0.3*inch))
    
    # OBS
    if dados_oc.get('obs'):
        Story.append(Paragraph(f"<b>Obs:</b> {dados_oc.get('obs')}", style_normal))
        Story.append(Spacer(1, 0.4*inch))
    
    # ASSINATURAS
    assinaturas = [
        [Paragraph('_______________________________', style_normal), Paragraph('_______________________________', style_normal)],
        [Paragraph('Assinatura do Conferente', style_normal), Paragraph('Responsável Compras/Financeiro', style_normal)],
    ]
    sign_table = Table(assinaturas, colWidths=[3.5*inch, 3.5*inch])
    sign_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    Story.append(sign_table)

    doc.build(Story)
    buffer.seek(0)
    return buffer.getvalue()

# ===================== SIDEBAR =====================
with st.sidebar:
    st.subheader("Parâmetros")
    h  = st.selectbox("Horizonte (dias)", [30, 60, 90], index=1, key="param_h")
    g  = st.number_input("Crescimento % ao mês", value=0.0, step=1.0, key="param_g")
    LT = st.number_input("Lead time (dias)", value=0, step=1, min_value=0, key="param_lt")
    st.markdown("---")
    if st.button("Carregar Padrão (Sheets)", use_container_width=True):
        try:
            cat, origem = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = cat.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = cat.kits_reais
            st.session_state.loaded_at = dt.datetime.now().strftime(f"%Y-%m-%d %H:%M:%S {origem}")
            st.success(f"Sucesso ({origem}).")
        except Exception as e: st.error(str(e))

# ===================== APP =====================
st.title("Reposição Logística — Alivvia (ERP V8.2)")

if st.session_state.catalogo_df is None:
    st.warning("► Carregue o **Padrão** no sidebar para começar.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📂 Dados", "🔍 Análise", "📝 Editor de OC", "🗂️ Gestão OCs", "📦 Alocação"])

# ---------- TAB 1: UPLOADS ----------
with tab1:
    c1, c2 = st.columns(2)
    def upload_block(emp, col):
        with col:
            st.subheader(emp)
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                f = st.file_uploader(f"{ft}", key=f"u_{emp}_{ft}")
                if f:
                    path_bin = get_local_file_path(emp, ft)
                    path_name = get_local_name_path(emp, ft)
                    with open(path_bin, 'wb') as fb: fb.write(f.read())
                    with open(path_name, 'w', encoding='utf-8') as fn: fn.write(f.name)
                    st.session_state[emp][ft].update({"name": f.name, "bytes": f.getvalue()})
                    st.success(f"Salvo: {f.name}")
                elif st.session_state[emp][ft]["name"]:
                    st.caption(f"✅ {st.session_state[emp][ft]['name']}")
    upload_block("ALIVVIA", c1)
    upload_block("JCA", c2)

# ---------- TAB 2: ANÁLISE ----------
with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        def run_calc(emp):
            d = st.session_state[emp]
            try:
                if not (d["FULL"]["bytes"] and d["VENDAS"]["bytes"]):
                    st.warning(f"Faltam arquivos para {emp}"); return
                
                full_raw = load_any_table_from_bytes(d["FULL"]["name"], d["FULL"]["bytes"])
                vend_raw = load_any_table_from_bytes(d["VENDAS"]["name"], d["VENDAS"]["bytes"])
                fis_bytes = d["ESTOQUE"]["bytes"]
                fis_raw = load_any_table_from_bytes(d["ESTOQUE"]["name"], fis_bytes) if fis_bytes else pd.DataFrame(columns=["sku","estoque"])

                full_df = mapear_colunas(full_raw, mapear_tipo(full_raw))
                vend_df = mapear_colunas(vend_raw, mapear_tipo(vend_raw))
                fis_df  = mapear_colunas(fis_raw, "FISICO") if fis_bytes else pd.DataFrame(columns=["SKU","Estoque_Fisico","Preco"])

                cat = Catalogo(st.session_state.catalogo_df.rename(columns={"sku":"component_sku"}), st.session_state.kits_df)
                res, _ = calcular(full_df, fis_df, vend_df, cat, st.session_state.param_h, st.session_state.param_g, st.session_state.param_lt)
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} Calculado!")
            except Exception as e: st.error(f"Erro {emp}: {e}")

        if c1.button("Gerar — ALIVVIA"): run_calc("ALIVVIA")
        if c2.button("Gerar — JCA"): run_calc("JCA")
        
        # V8.2: BOTÕES DE DOWNLOAD DA CURVA ABC
        st.write("---")
        abc_cols = st.columns(2)
        if st.session_state.resultado_ALIVVIA is not None:
            df_abc_A = gerar_curva_abc(st.session_state.resultado_ALIVVIA)
            if df_abc_A is not None:
                abc_cols[0].download_button(
                    "📥 Baixar Curva ABC (ALIVVIA)", 
                    exportar_csv_generico(df_abc_A), 
                    "curva_abc_alivvia.csv", 
                    "text/csv"
                )

        if st.session_state.resultado_JCA is not None:
            df_abc_J = gerar_curva_abc(st.session_state.resultado_JCA)
            if df_abc_J is not None:
                abc_cols[1].download_button(
                    "📥 Baixar Curva ABC (JCA)", 
                    exportar_csv_generico(df_abc_J), 
                    "curva_abc_jca.csv", 
                    "text/csv"
                )
        st.write("---")

        fc1, fc2 = st.columns(2)
        sku_filt = fc1.text_input("Filtro SKU", key="f_sku", on_change=reset_selection).upper().strip()
        
        df_A, df_J = st.session_state.resultado_ALIVVIA, st.session_state.resultado_JCA
        all_forns = []
        if df_A is not None: all_forns.extend(df_A["fornecedor"].unique())
        if df_J is not None: all_forns.extend(df_J["fornecedor"].unique())
        forn_opts = ["TODOS"] + sorted(list(set(all_forns)))
        forn_filt = fc2.selectbox("Fornecedor", forn_opts, key="f_forn", on_change=reset_selection)

        def show_table(df, key_sufix, sel_dict):
            if df is None: return
            df_view = df.copy()
            if sku_filt: df_view = df_view[df_view["SKU"].str.contains(sku_filt, na=False)]
            if forn_filt != "TODOS": df_view = df_view[df_view["fornecedor"] == forn_filt]
            
            df_view = enforce_numeric_types(df_view).drop_duplicates(subset=["SKU"]).reset_index(drop=True)
            
            key_skus = f"current_skus_{key_sufix}"
            st.session_state[key_skus] = df_view["SKU"].tolist()
            df_view["Selecionar"] = df_view["SKU"].map(lambda s: sel_dict.get(s, False))
            
            cols = ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"]
            
            st.data_editor(
                style_df_compra(df_view[cols]), 
                key=f"edit_{key_sufix}", 
                column_config={"Selecionar": st.column_config.CheckboxColumn(default=False), "Preco": st.column_config.Column("Valor Unit")},
                use_container_width=True, disabled=[c for c in cols if c != "Selecionar"], hide_index=True,
                on_change=callback_update_selection, args=(f"edit_{key_sufix}", key_skus, sel_dict)
            )

        st.caption("ALIVVIA"); show_table(df_A, "A", st.session_state.sel_A)
        st.caption("JCA"); show_table(df_J, "J", st.session_state.sel_J)

        # BOTÃO ENVIAR
        if st.button("📝 Enviar Selecionados para Editor de OC"):
            itens_to_add = []
            empresas_sel = []
            skus_existentes = [i['sku'] for i in st.session_state.pedido_ativo["itens"]]
            
            for emp, df, sel in [("ALIVVIA", df_A, st.session_state.sel_A), ("JCA", df_J, st.session_state.sel_J)]:
                if df is not None:
                    skus = [k for k,v in sel.items() if v]
                    sub = df[df["SKU"].isin(skus)].copy()
                    if not sub.empty:
                        empresas_sel.append(emp)
                        for _, row in sub.iterrows():
                            if row["SKU"] in skus_existentes: continue
                            qtd_final = int(row["Compra_Sugerida"])
                            if qtd_final <= 0: qtd_final = 1
                            itens_to_add.append({
                                "sku": row["SKU"],
                                "fornecedor": row["fornecedor"],
                                "qtd": qtd_final,
                                "valor_unit": float(row["Preco"])
                            })
                            skus_existentes.append(row["SKU"])
            
            if len(set(empresas_sel)) > 1 and not st.session_state.pedido_ativo["itens"]:
                st.error("Selecione itens de apenas UMA empresa para começar.")
            elif not itens_to_add:
                st.warning("Nenhum item NOVO selecionado.")
            else:
                if not st.session_state.pedido_ativo["itens"]:
                    forn_detectado = itens_to_add[0]["fornecedor"]
                    st.session_state.pedido_ativo["fornecedor"] = forn_detectado
                    st.session_state.pedido_ativo["empresa"] = empresas_sel[0]
                st.session_state.pedido_ativo["itens"].extend(itens_to_add)
                st.success(f"Sucesso! {len(itens_to_add)} novos itens no Editor.")

# ---------- TAB 3: EDITOR DE OC ----------
with tab3:
    st.header("Editor de Ordem de Compra")
    
    itens_atuais = st.session_state.pedido_ativo["itens"]
    has_itens = len(itens_atuais) > 0
    locked_forn = st.session_state.pedido_ativo["fornecedor"] if has_itens else None
    
    c1, c2, c3 = st.columns(3)
    
    idx_emp = 0 if st.session_state.pedido_ativo["empresa"] != "JCA" else 1
    empresa_oc = c1.selectbox("Empresa", ["ALIVVIA", "JCA"], index=idx_emp, disabled=has_itens)
    if has_itens: st.session_state.pedido_ativo["empresa"] = empresa_oc
    
    lista_forn = []
    if st.session_state.catalogo_df is not None:
        raw_list = st.session_state.catalogo_df["fornecedor"].unique().tolist()
        lista_forn = sorted([f for f in raw_list if f and str(f).strip() != ""])
    
    if locked_forn:
        c2.info(f"Fornecedor: **{locked_forn}**")
        fornecedor_oc = locked_forn
    else:
        fornecedor_oc = c2.selectbox("Selecione o Fornecedor", lista_forn)
        if not has_itens:
            st.session_state.pedido_ativo["fornecedor"] = fornecedor_oc
            st.session_state.pedido_ativo["empresa"] = empresa_oc

    # V8.0: O ID vem do Banco
    num_oc_prev = gerar_numero_oc(empresa_oc)
    c3.metric("Próximo Nº", num_oc_prev)
    st.divider()
    
    # ADD MANUAL
    if st.session_state.catalogo_df is not None:
        if not fornecedor_oc:
            st.warning("Selecione um Fornecedor acima.")
        else:
            cat_filtrado = st.session_state.catalogo_df[st.session_state.catalogo_df["fornecedor"] == fornecedor_oc].copy()
            if cat_filtrado.empty:
                st.warning(f"Sem produtos para {fornecedor_oc}")
            else:
                with st.expander(f"➕ Adicionar Produto Manualmente ({fornecedor_oc})", expanded=True):
                    skus_disponiveis = sorted(cat_filtrado["sku"].unique())
                    c_add1, c_add2, c_add3 = st.columns([3,1,1])
                    sku_add = c_add1.selectbox("Selecione o Produto", skus_disponiveis)
                    qtd_add = c_add2.number_input("Qtd", min_value=1, value=10)
                    if c_add3.button("Adicionar"):
                        existentes = [i['sku'] for i in st.session_state.pedido_ativo["itens"]]
                        if sku_add in existentes:
                            st.warning("Já está na lista!")
                        else:
                            preco_encontrado = buscar_preco_custo_profundo(sku_add)
                            st.session_state.pedido_ativo["itens"].append({
                                "sku": sku_add, "fornecedor": fornecedor_oc, "qtd": int(qtd_add), "valor_unit": float(preco_encontrado)
                            })
                            st.session_state.pedido_ativo["fornecedor"] = fornecedor_oc
                            st.session_state.pedido_ativo["empresa"] = empresa_oc
                            st.rerun()

    # Tabela
    if not itens_atuais:
        st.info("A OC está vazia.")
        if fornecedor_oc and not locked_forn:
            if st.button("Limpar Seleção de Fornecedor"):
                st.session_state.pedido_ativo["fornecedor"] = None; st.rerun()
    else:
        df_oc = pd.DataFrame(itens_atuais)
        df_oc["qtd"] = pd.to_numeric(df_oc["qtd"], errors='coerce').fillna(1).astype(int)
        df_oc["valor_unit"] = pd.to_numeric(df_oc["valor_unit"], errors='coerce').fillna(0.0).astype(float)
        df_oc["Total_Item"] = df_oc["qtd"] * df_oc["valor_unit"]
        
        edited_oc = st.data_editor(
            df_oc,
            column_config={
                "sku": st.column_config.TextColumn("SKU", disabled=True),
                "qtd": st.column_config.NumberColumn("Quantidade", min_value=1),
                "valor_unit": st.column_config.NumberColumn("Custo Unit (R$)", format="%.2f", min_value=0.0),
                "Total_Item": st.column_config.NumberColumn("Total (R$)", format="%.2f", disabled=True)
            },
            column_order=["sku", "qtd", "valor_unit", "Total_Item"],
            use_container_width=True, 
            num_rows="dynamic", 
            key="editor_oc_main",
            on_change=callback_editor_oc
        )
        
        total_oc_real = edited_oc["qtd"] * edited_oc["valor_unit"]
        total_oc_real_sum = total_oc_real.sum()
        colunas_essenciais = ["sku", "fornecedor", "qtd", "valor_unit"]
        
        if abs(total_oc_real_sum - df_oc["Total_Item"].sum()) > 0.01 or len(edited_oc) != len(df_oc):
            st.session_state.pedido_ativo["itens"] = edited_oc[colunas_essenciais].to_dict(orient="records")
            st.rerun()
        
        st.session_state.pedido_ativo["itens"] = edited_oc[colunas_essenciais].to_dict(orient="records")
        st.session_state.pedido_ativo["obs"] = st.session_state.get("obs_temp", "")

        cT1, cT2 = st.columns([3,1])
        obs_oc = cT1.text_area("Observações", value=st.session_state.pedido_ativo["obs"], key="obs_temp")
        cT2.metric("Valor Total", f"R$ {total_oc_real_sum:,.2f}")
        
        if cT2.button("💾 SALVAR OC OFICIAL (NUVEM)", type="primary"):
            if total_oc_real_sum <= 0:
                st.error("Valor total zerado.")
            else:
                nova_oc = {
                    "id": num_oc_prev, 
                    "empresa": empresa_oc, 
                    "fornecedor": fornecedor_oc,
                    "data_emissao": dt.datetime.now().strftime("%Y-%m-%d"),
                    "status": "PENDENTE", 
                    "obs": obs_oc,
                    "itens": st.session_state.pedido_ativo["itens"], 
                    "valor_total": float(total_oc_real_sum)
                }
                # V8.0: Salva no Supabase
                sucesso = salvar_pedido(nova_oc)
                if sucesso:
                    st.success(f"OC {num_oc_prev} Salva no Banco de Dados!")
                    st.session_state.pedido_ativo = {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}
                    time.sleep(1); st.rerun()

# ---------- TAB 4: GESTÃO OCS ----------
with tab4:
    st.header("Gerenciamento e Exportação de Pedidos")
    # V8.0: Lista do Supabase
    df_hist = listar_pedidos()
    
    if df_hist.empty:
        st.info("Nenhuma OC registrada no Banco de Dados.")
    else:
        # Filtros
        c_date1, c_date2 = st.columns(2)
        hj = dt.date.today()
        ini_date = c_date1.date_input("Data Início", value=hj - dt.timedelta(days=365))
        fim_date = c_date2.date_input("Data Fim", value=hj)
        
        c_filt1, c_filt2 = st.columns(2)
        f_status = c_filt1.radio("Filtro Status", ["Todos", "PENDENTE", "RECEBIDO"], horizontal=True)
        f_empresa = c_filt2.radio("Filtro Empresa", ["Todas", "ALIVVIA", "JCA"], horizontal=True)
        
        df_filt = df_hist.copy()
        df_filt["Data_Dt"] = pd.to_datetime(df_filt["Data"]).dt.date
        df_filt = df_filt[(df_filt["Data_Dt"] >= ini_date) & (df_filt["Data_Dt"] <= fim_date)]
        
        if f_status != "Todos": df_filt = df_filt[df_filt["Status"] == f_status]
        if f_empresa != "Todas": df_filt = df_filt[df_filt["Empresa"] == f_empresa]

        def format_status(val):
            if val == "PENDENTE": return "🟠 PENDENTE"
            if val == "RECEBIDO": return "🟢 RECEBIDO"
            return val
        
        df_view = df_filt[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status"]].copy()
        df_view
# ---------- TAB 5: ALOCAÇÃO DE CARGA (CALCULADORA DE RATEIO FINAL) ----------
with tab5:
    # IMPORTANTE: Requer que pd (pandas) já esteja importado no topo do arquivo.
    
    st.header("⚖️ Alocação de Compra (SKU por SKU)")
    st.caption("Insira a quantidade comprada de um SKU e o sistema calcula a divisão ideal entre ALIVVIA e JCA.")

    # 1. Carrega os resultados calculados
    df_a = st.session_state.get("resultado_ALIVVIA")
    df_j = st.session_state.get("resultado_JCA")

    if df_a is None or df_j is None:
        st.warning("⚠️ É necessário calcular as duas empresas (Alivvia e JCA) na aba 'Análise' primeiro.")
        st.stop() # Para o script se os dados não existirem.

    # --- PREPARAÇÃO DOS DADOS (Cálculo de Base) ---
    try:
        # Pega apenas as colunas essenciais para o rateio
        df_a_clean = df_a[["SKU", "Vendas_Total_60d", "Preco"]].rename(columns={"Vendas_Total_60d": "Vendas_A"})
        df_j_clean = df_j[["SKU", "Vendas_Total_60d", "Preco"]].rename(columns={"Vendas_Total_60d": "Vendas_J"})
        
        # Faz o cruzamento total (Outer Join)
        df_rateio_base = pd.merge(df_a_clean, df_j_clean, on="SKU", how="outer").fillna(0)
        df_rateio_base["Vendas_Total"] = df_rateio_base["Vendas_A"] + df_rateio_base["Vendas_J"]
        
        # Filtra apenas SKUs com algum histórico de venda (base de rateio)
        df_rateio_base = df_rateio_base[df_rateio_base["Vendas_Total"] > 0].copy()

        # Calcula a porcentagem de participação (% Share)
        df_rateio_base["% Alivvia"] = (df_rateio_base["Vendas_A"] / df_rateio_base["Vendas_Total"]) * 100
        df_rateio_base["% JCA"] = (df_rateio_base["Vendas_J"] / df_rateio_base["Vendas_Total"]) * 100
        
        skus_disponiveis = sorted(df_rateio_base["SKU"].unique().tolist())

    except Exception as e:
        st.error(f"Erro na preparação dos dados de rateio. Verifique as colunas na aba 'Análise'. Erro: {e}")
        st.stop()


    if not skus_disponiveis:
         st.info("Nenhum SKU tem histórico de vendas (Vendas 60d > 0) nas duas empresas para realizar o rateio.")
         st.stop() # Para o script se não houver base de rateio.
         
    # --- UI DE RATEIO (O fluxo que você pediu) ---
    c1, c2 = st.columns([2, 1])
    
    sku_selecionado = c1.selectbox(
        "Selecione o SKU para Ratear:", 
        skus_disponiveis, 
        key="rateio_sku"
    )
    
    qtd_comprada = c2.number_input(
        "Quantidade Comprada (Lote que Chegou):", 
        min_value=1, 
        value=100, 
        step=1, 
        key="rateio_qtd"
    )
    
    st.divider()

    # --- RESULTADO DO RATEIO ---
    if sku_selecionado and qtd_comprada > 0:
        # Pega a linha do SKU selecionado
        linha_sku = df_rateio_base[df_rateio_base["SKU"] == sku_selecionado].iloc[0]
        
        perc_alv = linha_sku["% Alivvia"] / 100
        perc_jca = linha_sku["% JCA"] / 100
        
        # Obtém o preço unitário para o cálculo do valor
        preco_alv = linha_sku['Preco_x'] if linha_sku['Preco_x'] > 0 else linha_sku['Preco_y']
        preco_jca = linha_sku['Preco_y'] if linha_sku['Preco_y'] > 0 else linha_sku['Preco_x']
        
        # Cálculos da Divisão
        qtd_alv_float = qtd_comprada * perc_alv
        qtd_jca_float = qtd_comprada * perc_jca
        
        # Arredondamento
        qtd_alv = int(round(qtd_alv_float))
        qtd_jca = int(round(qtd_jca_float))
        
        # Ajuste de arredondamento (para garantir que a soma seja igual à Qtd Comprada)
        sobra = qtd_comprada - (qtd_alv + qtd_jca)
        if sobra != 0:
            # Joga a diferença para quem tem a maior porcentagem
            if perc_alv >= perc_jca:
                qtd_alv += sobra
            else:
                qtd_jca += sobra

        col_res1, col_res2, col_res3 = st.columns(3)
        
        col_res1.metric(
            "Share (Alivvia)", 
            f"{linha_sku['% Alivvia']:.0f}%",
            help=f"Vendas Alivvia (60d): {linha_sku['Vendas_A']:.0f} un."
        )
        col_res2.metric(
            "Share (JCA)", 
            f"{linha_sku['% JCA']:.0f}%",
            help=f"Vendas JCA (60d): {linha_sku['Vendas_J']:.0f} un."
        )
        
        col_res3.metric(
            "Vendas Totais", 
            f"{linha_sku['Vendas_Total']:.0f} un.",
            help="Soma das vendas (60d) de ambas as empresas."
        )

        st.markdown("### Divisão da Carga:")

        col_div1, col_div2 = st.columns(2)
        
        # Usa o preço encontrado para calcular o Valor Total da alocação
        valor_alv = qtd_alv * preco_alv
        valor_jca = qtd_jca * preco_jca
        
        col_div1.metric(
            "📦 Enviar para ALIVVIA", 
            f"{qtd_alv} Unidades", 
            delta=f"Total: R$ {valor_alv:,.2f}"
        )
        
        col_div2.metric(
            "📦 Enviar para JCA", 
            f"{qtd_jca} Unidades", 
            delta=f"Total: R$ {valor_jca:,.2f}"
        )