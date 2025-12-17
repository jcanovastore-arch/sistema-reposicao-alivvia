import streamlit as st
import pandas as pd
from src import storage, logic, data, config, utils

st.set_page_config(page_title="Análise", layout="wide")
st.title("📊 Análise de Reposição")

# Sidebar configs
with st.sidebar:
    dias = st.selectbox("Dias", [30, 60, 90], index=1)
    cresc = st.number_input("Cresc %", 0.0)
    lead = st.number_input("Lead Time", 0)
    if st.button("🔄 Atualizar Catálogo"):
        c, _ = data.carregar_padrao_local_ou_sheets(config.DEFAULT_SHEET_LINK)
        st.session_state.catalogo = c

if not st.session_state.catalogo:
    st.warning("Carregue o catálogo na sidebar.")
    st.stop()

def calcular(emp):
    # 1. Baixa arquivos da nuvem
    raw_full = storage.download(f"{emp}/FULL.xlsx")
    raw_ext = storage.download(f"{emp}/EXT.xlsx")
    raw_fis = storage.download(f"{emp}/FISICO.xlsx")

    if not raw_full: return st.error(f"Falta Full {emp}")

    # 2. Processa
    df_f = logic.mapear_colunas(logic.smart_read_excel_csv(raw_full), "FULL")
    df_e = logic.mapear_colunas(logic.smart_read_excel_csv(raw_ext), "EXT") if raw_ext else pd.DataFrame()
    df_fis = logic.mapear_colunas(logic.smart_read_excel_csv(raw_fis), "FISICO") if raw_fis else pd.DataFrame()

    # 3. Calcula
    res = logic.calcular_reposicao(df_f, df_e, df_fis, st.session_state.catalogo, dias, cresc, lead)
    st.session_state[f"res_{emp}"] = res
    st.success(f"{emp} Atualizado!")

c1, c2 = st.columns(2)
if c1.button("CALCULAR ALIVVIA"): calcular("ALIVVIA")
if c2.button("CALCULAR JCA"): calcular("JCA")

st.divider()

# Exibição
for emp in ["ALIVVIA", "JCA"]:
    if f"res_{emp}" in st.session_state:
        st.subheader(emp)
        df = st.session_state[f"res_{emp}"].copy()
        
        # Colunas Separadas (O que você pediu)
        cols = ["SKU", "Vendas_Full", "Vendas_Ext", "Vendas_Total_60d", "Estoque_Full", "Estoque_Fisico", "Sugestao", "Preco"]
        
        df.insert(0, "Selecionar", False)
        edited = st.data_editor(
            df[["Selecionar"] + [c for c in cols if c in df.columns]],
            key=f"ed_{emp}",
            hide_index=True,
            column_config={"Selecionar": st.column_config.CheckboxColumn(default=False)}
        )
        
        if st.button(f"🛒 Add Selecionados ({emp})", key=f"add_{emp}"):
            sel = edited[edited["Selecionar"]==True]
            for _, r in sel.iterrows():
                # Lógica de Carrinho (Append na Session State Global)
                st.session_state.pedido.append({
                    "sku": r["SKU"], "qtd": int(r["Sugestao"]), "valor": float(r["Preco"]), "origem": emp
                })
            st.toast("Adicionado ao Editor de OC!")