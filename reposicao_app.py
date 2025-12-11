import os
import pandas as pd
import streamlit as st
import time
import datetime as dt

# Imports internos
from src.config import DEFAULT_SHEET_LINK
from src.utils import style_df_compra, norm_sku, format_br_currency
# Importando _carregar_padrao_de_content para permitir upload manual se o Google falhar
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets, _carregar_padrao_de_content
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

# ===================== ESTADO E SETUP =====================
def _ensure_state():
    defaults = {"catalogo_df": None, "kits_df": None, "resultado_ALIVVIA": None, "resultado_JCA": None, "sel_A": {}, "sel_J": {}, "pedido_ativo": {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    for emp in ["ALIVVIA", "JCA"]:
        if emp not in st.session_state: st.session_state[emp] = {}
        for ft in ["FULL", "VENDAS", "ESTOQUE"]:
            if ft not in st.session_state[emp]: st.session_state[emp][ft] = {"name": None, "bytes": None}
            # Tenta carregar cache local
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
    
def clear_file_cache(empresa, tipo):
    """Remove o arquivo .bin e .txt do cache local"""
    file_path = get_local_file_path(empresa, tipo)
    name_path = get_local_name_path(empresa, tipo)
    
    deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        deleted = True
    if os.path.exists(name_path):
        os.remove(name_path)
        deleted = True
        
    st.session_state[empresa][tipo]["name"] = None
    st.session_state[empresa][tipo]["bytes"] = None
    
    if deleted:
        st.toast(f"Cache de {empresa} {tipo} limpo!", icon="🧹")
        time.sleep(1)
        st.rerun()

# ===================== SIDEBAR =====================
with st.sidebar:
    st.header("⚙️ Parâmetros")
    h_p = st.selectbox("Horizonte (Dias)", [30, 60, 90], index=1)
    g_p = st.number_input("Crescimento %", value=0.0, step=0.5)
    lt_p = st.number_input("Lead Time", value=0, step=1)
    st.divider()
    
    st.subheader("📂 Dados Mestre")
    # Opção 1: Google Sheets (Automático)
    if st.button("🔄 Baixar do Google Sheets"):
        try:
            c, origem = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success(f"Carregado via {origem}!")
        except Exception as e: 
            st.error(f"Erro ao conectar no Google: {e}")
            st.warning("Use a opção de upload manual abaixo 👇")

    # Opção 2: Upload Manual (Caso o Google falhe)
    up_manual = st.file_uploader("Ou carregue 'Padrao_produtos.xlsx' manual:", type=["xlsx"])
    if up_manual:
        try:
            # Usa a função interna para processar o arquivo enviado manualmente
            c = _carregar_padrao_de_content(up_manual.getvalue())
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("✅ Arquivo carregado manualmente!")
        except Exception as e:
            st.error(f"Erro no arquivo: {e}")

st.title("Reposição Logística — Alivvia (Estável)")
if st.session_state.catalogo_df is None: st.warning("⚠️ Por favor, carregue o Padrão de Produtos no menu lateral (Google ou Upload).")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📂 Uploads", "🔍 Análise & Compra", "📝 Editor OC", "🗂️ Gestão", "📦 Alocação"])

# --- TAB 1: UPLOADS (COM BOTÃO DE LIMPEZA) ---
with tab1:
    c1, c2 = st.columns(2)
    def up_block(emp, col):
        with col:
            st.subheader(emp)
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                curr_state = st.session_state[emp][ft]
                
                f = st.file_uploader(ft, key=f"u_{emp}_{ft}")
                
                if f:
                    with open(get_local_file_path(emp, ft), 'wb') as fb: fb.write(f.read())
                    with open(get_local_name_path(emp, ft), 'w') as fn: fn.write(f.name)
                    st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue()}
                    st.success("Salvo!")
                
                if curr_state["name"]:
                    col_name, col_btn = st.columns([3, 1])
                    col_name.caption(f"✅ {curr_state['name']}")
                    if col_btn.button("🧹 Limpar", key=f"clean_{emp}_{ft}"):
                        clear_file_cache(emp, ft)

    up_block("ALIVVIA", c1); up_block("JCA", c2)

# --- TAB 2: ANÁLISE E COMPRA ---
with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        def run_calc(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]): return st.warning("Faltam arquivos.")
            try:
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

        # Filtros
        f1, f2 = st.columns(2)
        sku_f = f1.text_input("🔎 Filtro SKU", key="f_sku", on_change=reset_selection).upper()
        
        forns = set()
        if st.session_state.resultado_ALIVVIA is not None: forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].dropna().unique())
        if st.session_state.resultado_JCA is not None: forns.update(st.session_state.resultado_JCA["fornecedor"].dropna().unique())
        lista_forns = ["TODOS"] + sorted(list(forns))
        forn_f = f2.selectbox("🏭 Filtro Fornecedor", lista_forns, key="f_forn", on_change=reset_selection)
        
        for i, emp in enumerate(["ALIVVIA", "JCA"]):
            if st.session_state.get(f"resultado_{emp}") is not None:
                st.markdown(f"### 📊 {emp}")
                df = st.session_state[f"resultado_{emp}"].copy()
                
                if sku_f: df = df[df["SKU"].str.contains(sku_f, na=False)]
                if forn_f != "TODOS": df = df[df["fornecedor"] == forn_f]
                
                # Balanço
                if not df.empty:
                    m1, m2, m3, m4 = st.columns(4)
                    tot_fis = df['Estoque_Fisico'].sum()
                    val_fis = (df['Estoque_Fisico'] * df['Preco']).sum()
                    tot_full = df['Estoque_Full'].sum()
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
                        "Estoque_Fisico": st.column_config.NumberColumn("Físico (Bruto)", help="Estoque lido diretamente do arquivo.")
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
            dados = {"id": nid, "empresa": ped["empresa"], "fornecedor": ped["fornecedor"], "data_emissao": dt.date.today().strftime("%Y-%m-%d"), "valor_total": float(tot), "status": "Pendente", "obs": ped["obs"], "itens": ed.to_dict("records")}
            if salvar_pedido(dados):
                st.success(f"OC {nid} gerada!"); st.session_state.pedido_ativo["itens"] = []; time.sleep(1); st.rerun()
        if st.button("🗑️ Limpar"): st.session_state.pedido_ativo["itens"] = []; st.rerun()
    else: st.info("Carrinho vazio.")

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

# --- TAB 5: ALOCAÇÃO (Simplificada) ---
with tab5:
    st.header("📦 Alocação de Compra (JCA vs ALIVVIA)")
    
    ra = st.session_state.get("resultado_ALIVVIA")
    rj = st.session_state.get("resultado_JCA")
    
    if ra is None or rj is None:
        st.info("Por favor, calcule ambas as empresas na aba 'Análise' para alocar.")
    else:
        # Prepara base para alocação
        df_A = ra[["SKU", "Vendas_Total_60d", "Estoque_Fisico"]].rename(columns={"Vendas_Total_60d": "Vendas_A", "Estoque_Fisico": "Estoque_A"})
        df_J = rj[["SKU", "Vendas_Total_60d", "Estoque_Fisico"]].rename(columns={"Vendas_Total_60d": "Vendas_J", "Estoque_Fisico": "Estoque_J"})
        base_aloc = pd.merge(df_A, df_J, on="SKU", how="outer").fillna(0)
        
        sku_aloc = st.selectbox("Selecione o SKU para Alocar:", ["Selecione um SKU"] + base_aloc["SKU"].unique().tolist())
        
        if sku_aloc != "Selecione um SKU":
            row = base_aloc[base_aloc["SKU"] == sku_aloc].iloc[0]
            
            st.markdown("#### Detalhes do SKU")
            c1, c2, c3 = st.columns(3)
            c1.metric("Vendas ALIVVIA (60d)", int(row["Vendas_A"]))
            c2.metric("Vendas JCA (60d)", int(row["Vendas_J"]))
            c3.metric("Estoque Físico Total", int(row["Estoque_A"] + row["Estoque_J"]))
            
            st.markdown("---")
            compra_total = st.number_input(f"Quantidade TOTAL de Compra para {sku_aloc}:", min_value=1, step=1, value=500)
            
            venda_total = row["Vendas_A"] + row["Vendas_J"]
            
            if venda_total > 0:
                perc_A = row["Vendas_A"] / venda_total
                perc_J = row["Vendas_J"] / venda_total
            else:
                perc_A = 0.5
                perc_J = 0.5
            
            aloc_A = round(compra_total * perc_A)
            aloc_J = round(compra_total * perc_J)
            
            st.markdown("#### Alocação Sugerida (Baseado em % de Vendas 60d)")
            
            col_res1, col_res2 = st.columns(2)
            col_res1.metric("ALIVVIA (Qtd)", f"{aloc_A:,}".replace(",", "."))
            col_res2.metric("JCA (Qtd)", f"{aloc_J:,}".replace(",", "."))
            
            st.markdown("---")
            st.info("Esta alocação é apenas para fins de compra. As sugestões na aba 'Análise' consideram o estoque atual e a reserva.")