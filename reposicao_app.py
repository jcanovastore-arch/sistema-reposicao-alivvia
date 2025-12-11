import os
import pandas as pd
import streamlit as st
import time
import datetime as dt

# Imports internos
from src.config import DEFAULT_SHEET_LINK
from src.utils import style_df_compra, norm_sku, format_br_currency
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets
from src.logic import Catalogo, mapear_colunas, calcular
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

# ===================== SEGURANÇA =====================
if "password_correct" not in st.session_state: st.session_state.password_correct = False
if not st.session_state.password_correct:
    pwd = st.text_input("🔒 Senha:", type="password")
    if pwd == st.secrets["access"]["password"]:
        st.session_state.password_correct = True
        st.rerun()
    st.stop()

# ===================== ESTADO =====================
def _ensure_state():
    defaults = {
        "catalogo_df": None, "kits_df": None, 
        "resultado_ALIVVIA": None, "resultado_JCA": None, 
        "sel_A": {}, "sel_J": {}, 
        "current_skus_A": [], "current_skus_J": [],
        "pedido_ativo": {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    for emp in ["ALIVVIA", "JCA"]:
        if emp not in st.session_state: st.session_state[emp] = {}
        for ft in ["FULL", "VENDAS", "ESTOQUE"]:
            if ft not in st.session_state[emp]: st.session_state[emp][ft] = {"name": None, "bytes": None}
            if not st.session_state[emp][ft]["name"]:
                try:
                    p = get_local_file_path(emp, ft)
                    n = get_local_name_path(emp, ft)
                    if os.path.exists(p):
                        with open(p, 'rb') as f: st.session_state[emp][ft]["bytes"] = f.read()
                        with open(n, 'r') as f: st.session_state[emp][ft]["name"] = f.read().strip()
                except: pass
_ensure_state()

# ===================== FUNÇÕES UI =====================
def reset_selection(): st.session_state.sel_A = {}; st.session_state.sel_J = {}

def update_sel(k_wid, k_sku, d_sel):
    if k_wid not in st.session_state: return
    chg = st.session_state[k_wid]["edited_rows"]
    skus = st.session_state[k_sku]
    for i, c in chg.items():
        if "Selecionar" in c and i < len(skus): d_sel[skus[i]] = c["Selecionar"]

def add_to_cart(emp):
    sel = st.session_state[f"sel_{emp[0]}"]
    df = st.session_state[f"resultado_{emp}"]
    if df is None: return
    marcados = [k for k,v in sel.items() if v]
    if not marcados: return st.toast("Nada selecionado!")
    novos = df[df["SKU"].isin(marcados)]
    curr = st.session_state.pedido_ativo["itens"]
    curr_skus = [i["sku"] for i in curr]
    c = 0
    for _, r in novos.iterrows():
        if r["SKU"] not in curr_skus:
            curr.append({"sku": r["SKU"], "qtd": int(r["Compra_Sugerida"]), "valor_unit": float(r["Preco"]), "origem": emp})
            c += 1
    st.session_state.pedido_ativo["itens"] = curr
    if not st.session_state.pedido_ativo["fornecedor"] and not novos.empty:
        st.session_state.pedido_ativo["fornecedor"] = novos.iloc[0]["fornecedor"]
    st.toast(f"{c} itens adicionados!")

# ===================== SIDEBAR =====================
with st.sidebar:
    st.header("⚙️ Parâmetros")
    h_p = st.selectbox("Horizonte (Dias)", [30, 60, 90], index=1)
    g_p = st.number_input("Crescimento %", value=0.0, step=0.5)
    lt_p = st.number_input("Lead Time", value=0, step=1)
    st.divider()
    if st.button("🔄 Carregar Padrão"):
        try:
            c, _ = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("OK!")
        except Exception as e: st.error(str(e))

st.title("Reposição Logística — Alivvia (Restaurado)")
if st.session_state.catalogo_df is None: st.warning("Carregue o Padrão no menu lateral.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📂 Uploads", "🔍 Análise & Compra", "📝 Editor OC", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS ---
with tab1:
    c1, c2 = st.columns(2)
    def up_block(emp, col):
        with col:
            st.subheader(emp)
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                f = st.file_uploader(ft, key=f"u_{emp}_{ft}")
                if f:
                    with open(get_local_file_path(emp, ft), 'wb') as fb: fb.write(f.read())
                    with open(get_local_name_path(emp, ft), 'w') as fn: fn.write(f.name)
                    st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue()}
                    st.success("Salvo!")
                if st.session_state[emp][ft]["name"]: st.caption(f"✅ {st.session_state[emp][ft]['name']}")
    up_block("ALIVVIA", c1); up_block("JCA", c2)

# --- TAB 2: ANÁLISE E COMPRA ---
with tab2:
    if st.session_state.catalogo_df is not None:
        # Botões de Cálculo
        c1, c2 = st.columns(2)
        def run_calc(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]): return st.warning("Faltam arquivos.")
            try:
                # O logic.py corrigido vai ler os nomes limpos (estoque_atual) e retornar o valor puro
                full = mapear_colunas(load_any_table_from_bytes(s["FULL"]["name"], s["FULL"]["bytes"]), "FULL")
                vend = mapear_colunas(load_any_table_from_bytes(s["VENDAS"]["name"], s["VENDAS"]["bytes"]), "VENDAS")
                fis = pd.DataFrame()
                if s["ESTOQUE"]["bytes"]:
                    fis = mapear_colunas(load_any_table_from_bytes(s["ESTOQUE"]["name"], s["ESTOQUE"]["bytes"]), "FISICO")
                cat = Catalogo(st.session_state.catalogo_df.rename(columns={"sku":"component_sku"}), st.session_state.kits_df)
                res, _ = calcular(full, fis, vend, cat, h_p, g_p, lt_p)
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} OK!")
            except Exception as e: st.error(f"Erro: {e}")
        
        if c1.button("Calc ALIVVIA", use_container_width=True): run_calc("ALIVVIA")
        if c2.button("Calc JCA", use_container_width=True): run_calc("JCA")
        
        st.divider()

        # === FILTROS (RESTAURADOS) ===
        f1, f2 = st.columns(2)
        sku_f = f1.text_input("🔎 Filtro SKU (Ex: MINIBAND)", key="f_sku", on_change=reset_selection).upper()
        
        # Coleta lista de fornecedores de ambas as empresas
        forns = set()
        if st.session_state.resultado_ALIVVIA is not None: forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].dropna().unique())
        if st.session_state.resultado_JCA is not None: forns.update(st.session_state.resultado_JCA["fornecedor"].dropna().unique())
        lista_forns = ["TODOS"] + sorted(list(forns))
        
        forn_f = f2.selectbox("🏭 Filtro Fornecedor", lista_forns, key="f_forn", on_change=reset_selection)
        
        # Exibição dos Dados
        for i, emp in enumerate(["ALIVVIA", "JCA"]):
            if st.session_state.get(f"resultado_{emp}") is not None:
                st.markdown(f"### 📊 {emp}")
                df = st.session_state[f"resultado_{emp}"].copy()
                
                # Aplicação dos Filtros
                if sku_f: df = df[df["SKU"].str.contains(sku_f, na=False)]
                if forn_f != "TODOS": df = df[df["fornecedor"] == forn_f]
                
                # === BALANÇO (RESTAURADO) ===
                if not df.empty:
                    m1, m2, m3, m4 = st.columns(4)
                    tot_fis = df['Estoque_Fisico'].sum()
                    val_fis = (df['Estoque_Fisico'] * df['Preco']).sum()
                    tot_full = df['Estoque_Full'].sum()
                    # Valor Full Estimado
                    val_full = (df['Estoque_Full'] * df['Preco']).sum()

                    m1.metric("Físico (Un)", f"{int(tot_fis):,}".replace(",", "."))
                    m2.metric("Físico (R$)", format_br_currency(val_fis))
                    m3.metric("Full (Un)", f"{int(tot_full):,}".replace(",", "."))
                    m4.metric("Full (R$)", format_br_currency(val_full))
                
                # Tabela
                k_sku = f"current_skus_{emp}"
                st.session_state[k_sku] = df["SKU"].tolist()
                sel = st.session_state[f"sel_{emp[0]}"]
                df.insert(0, "Selecionar", df["SKU"].map(lambda x: sel.get(x, False)))
                
                cols = ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"]
                
                st.data_editor(
                    style_df_compra(df[cols]), 
                    key=f"ed_{emp}", 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Selecionar": st.column_config.CheckboxColumn(default=False),
                        "Estoque_Fisico": st.column_config.NumberColumn("Físico (Real)", help="Estoque lido do arquivo, sem descontos.")
                    },
                    on_change=update_sel, 
                    args=(f"ed_{emp}", k_sku, sel)
                )
                
                if st.button(f"🛒 Enviar Selecionados ({emp}) para Editor", key=f"bt_{emp}"): 
                    add_to_cart(emp)

# --- TAB 3: EDITOR ---
with tab3:
    st.header("📝 Editor de Ordem de Compra")
    ped = st.session_state.pedido_ativo
    c1, c2, c3 = st.columns(3)
    ped["fornecedor"] = c1.text_input("Fornecedor", ped["fornecedor"])
    ped["empresa"] = c2.selectbox("Empresa OC", ["ALIVVIA", "JCA"])
    ped["obs"] = c3.text_input("Obs", ped["obs"])
    
    if ped["itens"]:
        df_i = pd.DataFrame(ped["itens"])
        df_i["Total"] = df_i["qtd"] * df_i["valor_unit"]
        ed = st.data_editor(df_i, num_rows="dynamic", use_container_width=True, key="ed_oc")
        tot = ed["Total"].sum()
        st.metric("Total Pedido", format_br_currency(tot))
        
        if st.button("💾 Salvar OC", type="primary"):
            nid = gerar_numero_oc(ped["empresa"])
            dados = {
                "id": nid, "empresa": ped["empresa"], "fornecedor": ped["fornecedor"],
                "data_emissao": dt.date.today().strftime("%Y-%m-%d"), "valor_total": float(tot),
                "status": "Pendente", "obs": ped["obs"], "itens": ed.to_dict("records")
            }
            if salvar_pedido(dados):
                st.success(f"OC {nid} gerada!"); st.session_state.pedido_ativo["itens"] = []; time.sleep(1); st.rerun()
        if st.button("🗑️ Limpar"): st.session_state.pedido_ativo["itens"] = []; st.rerun()
    else: st.info("Carrinho vazio. Selecione itens na aba 'Análise'.")

# --- TAB 4: GESTÃO ---
with tab4:
    st.header("🗂️ Gestão de OCs")
    if st.button("🔄 Atualizar Lista"): st.rerun()
    df_ocs = listar_pedidos()
    if not df_ocs.empty:
        st.dataframe(df_ocs[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Obs"]], use_container_width=True, hide_index=True)
        c_a1, c_a2 = st.columns(2)
        sel_oc = c_a1.selectbox("Selecione ID", df_ocs["ID"].unique())
        if sel_oc:
            row = df_ocs[df_ocs["ID"] == sel_oc].iloc[0]
            ns = c_a2.selectbox("Novo Status", ["Pendente", "Aprovado", "Enviado", "Recebido", "Cancelado"])
            if c_a2.button("Atualizar Status"): atualizar_status(sel_oc, ns); st.success("Ok!"); time.sleep(1); st.rerun()
            
            with st.expander("Ver Itens"):
                itens = row["Dados_Completos"]
                if isinstance(itens, list) and len(itens) > 0: st.table(pd.DataFrame(itens))
                else: st.write("Sem detalhes.")
            
            if st.button("Excluir"): excluir_pedido_db(sel_oc); st.warning("Excluído"); time.sleep(1); st.rerun()

# --- TAB 5: ALOCAÇÃO (RESTAURADA - LÓGICA DE TRANSFERÊNCIA) ---
with tab5:
    st.header("📦 Alocação e Transferência (JCA ↔ ALIVVIA)")
    
    ra = st.session_state.get("resultado_ALIVVIA")
    rj = st.session_state.get("resultado_JCA")
    
    if ra is not None and rj is not None:
        # Filtros também aqui
        f_aloc1, f_aloc2 = st.columns(2)
        sku_aloc = f_aloc1.text_input("Filtro SKU (Alocação)", key="f_sku_aloc").upper()
        
        # Prepara dados
        cols_key = ["SKU", "Estoque_Fisico", "Reserva_30d", "Necessidade", "Compra_Sugerida"]
        da = ra[cols_key].set_index("SKU").add_suffix("_A")
        dj = rj[cols_key].set_index("SKU").add_suffix("_J")
        
        # Merge
        dm = pd.merge(da, dj, left_index=True, right_index=True, how="outer").fillna(0)
        
        # Cálculo de Saldo (O que tenho - O que preciso guardar)
        # Saldo Positivo = Sobra. Saldo Negativo = Falta Real.
        dm["Saldo_A"] = dm["Estoque_Fisico_A"] - dm["Reserva_30d_A"]
        dm["Saldo_J"] = dm["Estoque_Fisico_J"] - dm["Reserva_30d_J"]
        
        # Lógica de Transferência
        # Se A tem sobra (>0) e J tem falta (<0), Sugere A->J
        # Se J tem sobra (>0) e A tem falta (<0), Sugere J->A
        
        def calc_transf(row):
            s_a = row["Saldo_A"]
            s_j = row["Saldo_J"]
            
            # Caso 1: A sobra, J falta
            if s_a > 0 and s_j < 0:
                qtd = min(s_a, abs(s_j))
                return f"Transf. A -> J ({int(qtd)})"
            
            # Caso 2: J sobra, A falta
            elif s_j > 0 and s_a < 0:
                qtd = min(s_j, abs(s_a))
                return f"Transf. J -> A ({int(qtd)})"
            
            return "-"

        dm["Sugestão"] = dm.apply(calc_transf, axis=1)
        
        # Filtra SKU
        if sku_aloc:
            dm = dm[dm.index.str.contains(sku_aloc, na=False)]
            
        # Filtra apenas quem tem ação (Transferência ou Compra)
        # Mostra tudo para conferencia, mas ordena por sugestão
        dm = dm.sort_values("Sugestão", ascending=False)
        
        st.dataframe(
            dm[["Estoque_Fisico_A", "Necessidade_A", "Saldo_A", 
                "Estoque_Fisico_J", "Necessidade_J", "Saldo_J", 
                "Sugestão"]], 
            use_container_width=True
        )
        
        st.caption("Legenda: Saldo positivo = Sobra (Estoque > Reserva). Saldo negativo = Falta. Sugestão tenta cobrir a falta de um com a sobra do outro.")
        
    else:
        st.info("Por favor, calcule ambas as empresas na aba 'Análise' para gerar a alocação cruzada.")