import streamlit as st
from src.logic import calcular_reposicao
from src.data import carregar_bases_para_calculo
from src import utils
import pandas as pd 
import numpy as np

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Reposição Integrado")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Parâmetros")
    dias_horizonte = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    crescimento = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead_time = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    # CORREÇÃO AQUI: Removidas as barras invertidas que causavam o erro
    if st.button("🔄 Recalcular", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --- VERIFICAÇÃO ---
dados_catalogo = st.session_state.get('catalogo_dados')
if dados_catalogo is None:
    st.warning("⚠️ Catálogo não carregado. Carregue na Home.")
    st.stop()

# --- CÁLCULO ---
@st.cache_data(ttl=600)
def calcular_tudo(dias, cresc, lead):
    res = {}
    for emp in ["ALIVVIA", "JCA"]:
        bases = carregar_bases_para_calculo(emp)
        if bases:
            res[emp] = calcular_reposicao(
                bases["df_full"], bases["df_fisico"], bases["df_ext"],
                bases["catalogo_kits"], bases["catalogo_simples"], emp,
                dias, cresc, lead
            )
    return res

with st.spinner("Processando..."):
    resultados = calcular_tudo(dias_horizonte, crescimento, lead_time)

if not resultados:
    st.error("Uploads pendentes na aba 1.")
    st.stop()

# --- FILTROS ---
forns_a = resultados.get("ALIVVIA", pd.DataFrame())
forns_j = resultados.get("JCA", pd.DataFrame())
lista_a = forns_a['Fornecedor'].dropna().unique() if not forns_a.empty else []
lista_j = forns_j['Fornecedor'].dropna().unique() if not forns_j.empty else []
todos_fornecedores = sorted(list(set(lista_a) | set(lista_j)))

c_filtro1, c_filtro2 = st.columns([1, 1])
sel_fornecedor = c_filtro1.multiselect("Filtrar Fornecedor:", options=todos_fornecedores)
busca_sku = c_filtro2.text_input("Buscar SKU:").upper()

# --- EXIBIÇÃO POR EMPRESA ---
def exibir_painel_empresa(nome_empresa, df_original, filtro_forn, filtro_sku):
    st.markdown("---")
    st.subheader(f"🏢 {nome_empresa}")
    
    df = df_original.copy()
    if filtro_forn: df = df[df['Fornecedor'].isin(filtro_forn)]
    if filtro_sku: df = df[df['SKU'].str.contains(filtro_sku, na=False)]
        
    if df.empty:
        st.info("Sem dados.")
        return

    # --- KPIs DE ESTOQUE ---
    qtd_fisico = df['Estoque_Fisico'].sum()
    val_fisico = (df['Estoque_Fisico'] * df['Preco_Custo']).sum()
    
    qtd_full = df['Estoque_Full'].sum()
    val_full = (df['Estoque_Full'] * df['Preco_Custo']).sum()
    
    sugestao_total = df['Valor_Compra'].sum()
    pecas_comprar = df['Compra_Sugerida'].sum()

    # Layout de Métricas
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Estoque Físico (Qtd)", f"{int(qtd_fisico):,}".replace(",", "."))
    k2.metric("Estoque Físico (R$)", utils.format_br_currency(val_fisico))
    k3.metric("Estoque Full (Qtd)", f"{int(qtd_full):,}".replace(",", "."))
    k4.metric("Estoque Full (R$)", utils.format_br_currency(val_full))
    k5.metric("Sugestão Compra (R$)", utils.format_br_currency(sugestao_total))
    
    # --- TABELA ---
    colunas = [
        'SKU', 'Fornecedor', 
        'Estoque_Fisico', 'Estoque_Full', 
        'Vendas_Full_60d', 'Vendas_Shopee_60d', 
        'Venda_Diaria',
        'Compra_Sugerida', 'Valor_Compra', 'Preco_Custo'
    ]
    
    df_view = df[(df['Estoque_Total'] > 0) | (df['Compra_Sugerida'] > 0) | (df['Vendas_Total_Global_60d'] > 0)]
    df_view = df_view.sort_values(['Valor_Compra', 'Fornecedor'], ascending=[False, True])
    
    st.dataframe(
        df_view[colunas],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Vendas_Full_60d": st.column_config.NumberColumn("ML (60d)", format="%d"),
            "Vendas_Shopee_60d": st.column_config.NumberColumn("Shopee (60d)", format="%d"),
            "Venda_Diaria": st.column_config.NumberColumn("Média/Dia", format="%.1f"),
            "Estoque_Full": st.column_config.NumberColumn("Full", format="%d"),
            "Estoque_Fisico": st.column_config.NumberColumn("Físico", format="%d"),
            "Compra_Sugerida": st.column_config.NumberColumn("COMPRAR", format="%d"),
            "Valor_Compra": st.column_config.NumberColumn("Total R$", format="R$ %.2f"),
            "Preco_Custo": st.column_config.NumberColumn("Custo", format="R$ %.2f"),
        }
    )

if "ALIVVIA" in resultados: exibir_painel_empresa("ALIVVIA", resultados["ALIVVIA"], sel_fornecedor, busca_sku)
if "JCA" in resultados: exibir_painel_empresa("JCA", resultados["JCA"], sel_fornecedor, busca_sku)