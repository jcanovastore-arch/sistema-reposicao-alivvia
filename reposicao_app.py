import os
import datetime as dt
import pandas as pd
import streamlit as st
import numpy as np
import time

# Imports internos
from src.config import DEFAULT_SHEET_LINK
from src.utils import style_df_compra, norm_sku, format_br_currency
from src.data import get_local_file_path, get_local_name_path, load_any_table_from_bytes, carregar_padrao_local_ou_sheets
from src.logic import Catalogo, mapear_colunas, calcular
from src.orders_db import gerar_numero_oc, salvar_pedido, listar_pedidos, atualizar_status, excluir_pedido_db

# ===================== CONFIGURAÇÃO =====================
st.set_page_config(page_title="Reposição Logística — Alivvia", layout="wide")

if "password_correct" not in st.session_state: st.session_state.password_correct = False

def check_password():
    if st.session_state.password_correct: return True
    pwd = st.text_input("🔒 Senha de Acesso:", type="password")
    if pwd == st.secrets["access"]["password"]:
        st.session_state.password_correct = True
        st.rerun()
    return False

if not check_password(): st.stop()

# ===================== INICIALIZAÇÃO =====================
def _ensure_state():
    defaults = {
        "catalogo_df": None, "kits_df": None, 
        "resultado_ALIVVIA": None, "resultado_JCA": None,
        "sel_A": {}, "sel_J": {}, 
        "current_skus_A": [], "current_skus_J": [],
        # Estado do Pedido Ativo
        "pedido_ativo": {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

    for emp in ["ALIVVIA", "JCA"]:
        if emp not in st.session_state: st.session_state[emp] = {}
        for ft in ["FULL", "VENDAS", "ESTOQUE"]:
            if ft not in st.session_state[emp]:
                st.session_state[emp][ft] = {"name": None, "bytes": None}
            if not st.session_state[emp][ft]["name"]:
                p_bin = get_local_file_path(emp, ft)
                p_nam = get_local_name_path(emp, ft)
                if os.path.exists(p_bin) and os.path.exists(p_nam):
                    try:
                        with open(p_bin, 'rb') as f: st.session_state[emp][ft]["bytes"] = f.read()
                        with open(p_nam, 'r') as f: st.session_state[emp][ft]["name"] = f.read().strip()
                    except: pass

_ensure_state()

# ===================== FUNÇÕES DE INTERFACE =====================
def reset_selection():
    st.session_state.sel_A = {}
    st.session_state.sel_J = {}

def callback_update_selection(key_widget, key_skus, sel_dict):
    if key_widget not in st.session_state: return
    changes = st.session_state[key_widget]["edited_rows"]
    current_skus = st.session_state[key_skus]
    for idx, change in changes.items():
        if "Selecionar" in change:
            if idx < len(current_skus):
                sku_clicado = current_skus[idx]
                sel_dict[sku_clicado] = change["Selecionar"]

def adicionar_selecionados_ao_pedido(empresa_origem):
    """Pega os itens marcados na Tab 2 e joga para o Editor na Tab 3"""
    sel_dict = st.session_state[f"sel_{empresa_origem[0]}"]
    df_res = st.session_state[f"resultado_{empresa_origem}"]
    
    if df_res is None: return
    
    skus_marcados = [k for k, v in sel_dict.items() if v]
    if not skus_marcados:
        st.toast("Nenhum item selecionado!", icon="⚠️")
        return

    # Filtra os dados
    itens_novos = df_res[df_res["SKU"].isin(skus_marcados)].copy()
    
    count = 0
    lista_atual = st.session_state.pedido_ativo["itens"]
    skus_no_carrinho = [i["sku"] for i in lista_atual]
    
    for _, row in itens_novos.iterrows():
        if row["SKU"] not in skus_no_carrinho:
            lista_atual.append({
                "sku": row["SKU"],
                "qtd": int(row["Compra_Sugerida"]),
                "valor_unit": float(row["Preco"]),
                "origem": empresa_origem
            })
            count += 1
            
    st.session_state.pedido_ativo["itens"] = lista_atual
    
    # Tenta definir fornecedor automaticamente se estiver vazio
    if not st.session_state.pedido_ativo["fornecedor"] and not itens_novos.empty:
        st.session_state.pedido_ativo["fornecedor"] = itens_novos.iloc[0]["fornecedor"]
        
    st.toast(f"{count} itens enviados para o Editor!", icon="🛒")

# ===================== SIDEBAR =====================
with st.sidebar:
    st.header("⚙️ Parâmetros")
    h_param = st.selectbox("Horizonte (Dias)", [30, 60, 90], index=1)
    g_param = st.number_input("Crescimento (% a.m.)", value=0.0, step=0.5)
    lt_param = st.number_input("Lead Time (Dias)", value=0, step=1)
    
    st.divider()
    if st.button("🔄 Carregar Padrão (Sheets)", use_container_width=True):
        try:
            c, _ = carregar_padrao_local_ou_sheets(DEFAULT_SHEET_LINK)
            st.session_state.catalogo_df = c.catalogo_simples.rename(columns={"component_sku":"sku"})
            st.session_state.kits_df = c.kits_reais
            st.success("Padrão Atualizado!")
        except Exception as e: st.error(str(e))

# ===================== APP PRINCIPAL =====================
st.title("Reposição Logística — Alivvia (Sistema Completo)")

if st.session_state.catalogo_df is None:
    st.warning("⚠️ Carregue o **Padrão** no menu lateral.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📂 Dados", "🔍 Análise", "📝 Editor de OC", "🗂️ Gestão OCs", "📦 Alocação"])

# --- TAB 1: UPLOADS ---
with tab1:
    c1, c2 = st.columns(2)
    def upload_card(emp, col):
        with col:
            st.subheader(f"Dados: {emp}")
            for ft in ["FULL", "VENDAS", "ESTOQUE"]:
                f = st.file_uploader(f"{ft}", key=f"u_{emp}_{ft}")
                if f:
                    p_bin = get_local_file_path(emp, ft)
                    p_nam = get_local_name_path(emp, ft)
                    with open(p_bin, 'wb') as fb: fb.write(f.read())
                    with open(p_nam, 'w') as fn: fn.write(f.name)
                    st.session_state[emp][ft] = {"name": f.name, "bytes": f.getvalue()}
                    st.success("Salvo!")
                if st.session_state[emp][ft]["name"]:
                    st.caption(f"✅ {st.session_state[emp][ft]['name']}")
    upload_card("ALIVVIA", c1)
    upload_card("JCA", c2)

# --- TAB 2: CÁLCULO ---
with tab2:
    if st.session_state.catalogo_df is not None:
        c1, c2 = st.columns(2)
        
        def processar(emp):
            s = st.session_state[emp]
            if not (s["FULL"]["bytes"] and s["VENDAS"]["bytes"]):
                st.warning(f"Faltam arquivos para {emp}"); return
            try:
                full_raw = load_any_table_from_bytes(s["FULL"]["name"], s["FULL"]["bytes"])
                vend_raw = load_any_table_from_bytes(s["VENDAS"]["name"], s["VENDAS"]["bytes"])
                fis_raw  = pd.DataFrame()
                if s["ESTOQUE"]["bytes"]:
                    fis_raw = load_any_table_from_bytes(s["ESTOQUE"]["name"], s["ESTOQUE"]["bytes"])

                full_df = mapear_colunas(full_raw, "FULL")
                vend_df = mapear_colunas(vend_raw, "VENDAS")
                fis_df  = mapear_colunas(fis_raw, "FISICO") if not fis_raw.empty else pd.DataFrame()
                
                cat = Catalogo(st.session_state.catalogo_df.rename(columns={"sku":"component_sku"}), st.session_state.kits_df)
                res, _ = calcular(full_df, fis_df, vend_df, cat, h=h_param, g=g_param, LT=lt_param)
                
                st.session_state[f"resultado_{emp}"] = res
                st.success(f"{emp} Atualizado!")
            except Exception as e: st.error(f"Erro: {e}")

        if c1.button("Calcular ALIVVIA", use_container_width=True): processar("ALIVVIA")
        if c2.button("Calcular JCA", use_container_width=True): processar("JCA")
        
        st.divider()
        
        # Filtros e Tabela
        fc1, fc2 = st.columns(2)
        sku_filt = fc1.text_input("Filtro SKU", key="f_sku", on_change=reset_selection).upper().strip()
        
        # Coleta fornecedores
        all_forns = set()
        if st.session_state.resultado_ALIVVIA is not None: all_forns.update(st.session_state.resultado_ALIVVIA["fornecedor"].unique())
        if st.session_state.resultado_JCA is not None: all_forns.update(st.session_state.resultado_JCA["fornecedor"].unique())
        forn_opts = ["TODOS"] + sorted(list(all_forns))
        forn_filt = fc2.selectbox("Fornecedor", forn_opts, key="f_forn", on_change=reset_selection)
        
        col_res1, col_res2 = st.columns(2)
        
        for idx, emp in enumerate(["ALIVVIA", "JCA"]):
            with (col_res1 if idx == 0 else col_res2):
                res = st.session_state.get(f"resultado_{emp}")
                if res is not None:
                    st.markdown(f"### {emp}")
                    
                    df_view = res.copy()
                    if sku_filt: df_view = df_view[df_view["SKU"].str.contains(sku_filt, na=False)]
                    if forn_filt != "TODOS": df_view = df_view[df_view["fornecedor"] == forn_filt]
                    
                    # Balanço
                    c_m1, c_m2 = st.columns(2)
                    tot_fis = int(df_view["Estoque_Fisico"].sum())
                    tot_full = int(df_view["Estoque_Full"].sum())
                    c_m1.metric("Total Físico", f"{tot_fis:,}".replace(",", "."))
                    c_m2.metric("Total Full", f"{tot_full:,}".replace(",", "."))
                    
                    # Tabela
                    key_skus = f"current_skus_{emp}"
                    sel_dict = st.session_state[f"sel_{emp[0]}"]
                    
                    df_view = df_view.drop_duplicates(subset=["SKU"]).reset_index(drop=True)
                    st.session_state[key_skus] = df_view["SKU"].tolist()
                    
                    df_view.insert(0, "Selecionar", df_view["SKU"].map(lambda s: sel_dict.get(s, False)))
                    
                    cols_view = ["Selecionar", "SKU", "fornecedor", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Preco", "Compra_Sugerida", "Valor_Compra_R$"]
                    
                    st.data_editor(
                        style_df_compra(df_view[cols_view]),
                        key=f"edit_{emp}",
                        column_config={"Selecionar": st.column_config.CheckboxColumn(default=False)},
                        use_container_width=True,
                        hide_index=True,
                        on_change=callback_update_selection,
                        args=(f"edit_{emp}", key_skus, sel_dict)
                    )
                    
                    if st.button(f"Enviar Selecionados ({emp})", key=f"btn_send_{emp}"):
                        adicionar_selecionados_ao_pedido(emp)

# --- TAB 3: EDITOR DE OC (Restaurado) ---
with tab3:
    st.header("📝 Editor de Ordem de Compra")
    
    pedido = st.session_state.pedido_ativo
    
    col_e1, col_e2, col_e3 = st.columns(3)
    novo_forn = col_e1.text_input("Fornecedor:", value=pedido["fornecedor"] or "")
    empresa_oc = col_e2.selectbox("Empresa da OC:", ["ALIVVIA", "JCA"], index=0)
    obs_oc = col_e3.text_input("Observações:", value=pedido["obs"])
    
    st.session_state.pedido_ativo["fornecedor"] = novo_forn
    st.session_state.pedido_ativo["empresa"] = empresa_oc
    st.session_state.pedido_ativo["obs"] = obs_oc
    
    if not pedido["itens"]:
        st.info("O carrinho está vazio. Selecione itens na aba 'Análise'.")
    else:
        df_itens = pd.DataFrame(pedido["itens"])
        df_itens["Total (R$)"] = df_itens["qtd"] * df_itens["valor_unit"]
        
        # Edição
        edited_df = st.data_editor(
            df_itens,
            num_rows="dynamic",
            column_config={
                "sku": "SKU",
                "qtd": st.column_config.NumberColumn("Qtd", step=1),
                "valor_unit": st.column_config.NumberColumn("Unitário (R$)", format="R$ %.2f"),
                "Total (R$)": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
                "origem": "Origem Sugestão"
            },
            use_container_width=True,
            key="editor_oc_main"
        )
        
        # Sincroniza edições de volta ao session_state
        # (Lógica simplificada: assume que o usuário edita e clica em salvar)
        
        total_oc = edited_df["Total (R$)"].sum()
        st.metric("Valor Total do Pedido", format_br_currency(total_oc))
        
        if st.button("💾 Salvar Ordem de Compra", type="primary", use_container_width=True):
            if not novo_forn:
                st.error("Preencha o Fornecedor!")
            else:
                novo_id = gerar_numero_oc(empresa_oc)
                dados_finais = {
                    "id": novo_id,
                    "empresa": empresa_oc,
                    "fornecedor": novo_forn,
                    "data_emissao": dt.date.today().strftime("%Y-%m-%d"),
                    "valor_total": float(total_oc),
                    "status": "Pendente",
                    "obs": obs_oc,
                    "itens": edited_df.to_dict("records")
                }
                
                if salvar_pedido(dados_finais):
                    st.success(f"Pedido {novo_id} salvo com sucesso!")
                    st.session_state.pedido_ativo = {"itens": [], "fornecedor": None, "empresa": None, "obs": ""}
                    time.sleep(1)
                    st.rerun()

        if st.button("🗑️ Limpar Carrinho"):
            st.session_state.pedido_ativo["itens"] = []
            st.rerun()

# --- TAB 4: GESTÃO (Restaurado) ---
with tab4:
    st.header("🗂️ Histórico de Pedidos")
    
    if st.button("🔄 Atualizar Lista"):
        st.rerun()
        
    df_ocs = listar_pedidos()
    
    if df_ocs.empty:
        st.info("Nenhuma OC encontrada no banco de dados.")
    else:
        # Filtros de Gestão
        st.dataframe(
            df_ocs[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Obs"]],
            use_container_width=True,
            hide_index=True
        )
        
        st.divider()
        st.subheader("Ações")
        
        col_act1, col_act2 = st.columns(2)
        oc_selecionada = col_act1.selectbox("Selecione a OC para alterar:", df_ocs["ID"].unique())
        
        if oc_selecionada:
            novo_status = col_act2.selectbox("Novo Status:", ["Pendente", "Aprovado", "Enviado", "Recebido", "Cancelado"])
            if col_act2.button("Atualizar Status"):
                atualizar_status(oc_selecionada, novo_status)
                st.success("Status atualizado!")
                time.sleep(1)
                st.rerun()
                
            with st.expander("Ver Detalhes dos Itens"):
                row = df_ocs[df_ocs["ID"] == oc_selecionada].iloc[0]
                itens = row["Dados_Completos"].get("itens", [])
                st.table(pd.DataFrame(itens))
                
            if st.button("❌ Excluir OC Definitivamente"):
                excluir_pedido_db(oc_selecionada)
                st.warning("OC Excluída.")
                time.sleep(1)
                st.rerun()

# --- TAB 5: ALOCAÇÃO (Visão Consolidada) ---
with tab5:
    st.header("📦 Visão de Alocação (JCA vs ALIVVIA)")
    
    res_A = st.session_state.get("resultado_ALIVVIA")
    res_J = st.session_state.get("resultado_JCA")
    
    if res_A is not None and res_J is not None:
        # Merge das duas visões
        df_A = res_A[["SKU", "Compra_Sugerida"]].rename(columns={"Compra_Sugerida": "Compra_ALIVVIA"})
        df_J = res_J[["SKU", "Compra_Sugerida"]].rename(columns={"Compra_Sugerida": "Compra_JCA"})
        
        df_aloc = pd.merge(df_A, df_J, on="SKU", how="outer").fillna(0)
        df_aloc["Total_Compra"] = df_aloc["Compra_ALIVVIA"] + df_aloc["Compra_JCA"]
        
        # Filtra só o que tem compra
        df_aloc = df_aloc[df_aloc["Total_Compra"] > 0].sort_values("Total_Compra", ascending=False)
        
        st.dataframe(df_aloc, use_container_width=True)
    else:
        st.info("Calcule ambas as empresas na aba 'Análise' para ver a alocação consolidada.")