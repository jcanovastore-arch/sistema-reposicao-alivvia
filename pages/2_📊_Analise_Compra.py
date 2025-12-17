import streamlit as st
import pandas as pd
from src.logic import calcular_reposicao

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Compras Integrado")

# --- FILTROS GLOBAIS NA SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parâmetros de Compra")
    dias_h = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    cresc = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Filtros Unificados")
    f_sku = st.text_input("Filtrar SKU (Global)").strip().upper()
    
    if st.button("🔄 Recalcular Tudo", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

@st.cache_data
def carregar_dados_unificados(d, c, l):
    # Retorna os DataFrames calculados ou None se falhar
    return {
        "ALIVVIA": calcular_reposicao("ALIVVIA", d, c, l),
        "JCA": calcular_reposicao("JCA", d, c, l)
    }

resultados = carregar_dados_unificados(dias_h, cresc, lead)

# Colunas na ordem solicitada por você
colunas_exigidas = [
    "SKU", "Fornecedor", "Preço de custo", 
    "Vendas full", "vendas Shopee", 
    "Estoque full (Un)", "Valor Estoque Full",
    "Estoque fisico (Un)", "Valor Estoque Fisico",
    "Compra sugerida", "Valor total da compra sugerida"
]

# --- CORREÇÃO DO VALUEERROR: Verificação robusta de dicionário e DataFrames ---
tem_dados = False
if resultados:
    for emp in resultados:
        if resultados[emp] is not None and not resultados[emp].empty:
            tem_dados = True
            break

if not tem_dados:
    st.warning("⚠️ Sem dados processados. Certifique-se de que os arquivos estão no Supabase e o Catálogo foi carregado.")
else:
    # FILTRO DE FORNECEDOR GLOBAL (Busca em todas as empresas)
    todos_forn = []
    for emp in resultados:
        df_temp = resultados[emp]
        if df_temp is not None and not df_temp.empty:
            todos_forn.extend(df_temp['Fornecedor'].dropna().unique())
    
    lista_forn_global = sorted([str(x) for x in set(todos_forn) if str(x) != "0" and str(x) != "nan"])
    
    with st.sidebar:
        sel_forn_global = st.multiselect("Filtrar Fornecedor (Global)", lista_forn_global)

    # EXIBIÇÃO DAS DUAS EMPRESAS (SEMPRE ABERTAS)
    for emp in ["ALIVVIA", "JCA"]:
        df = resultados.get(emp)
        
        # Só renderiza se o DataFrame existir e tiver dados
        if df is not None and not df.empty:
            st.subheader(f"🏢 Empresa: {emp}")
            
            # Aplicar Filtros Globais (SKU e Fornecedor)
            if f_sku:
                df = df[df['SKU'].str.contains(f_sku, na=False)]
            if sel_forn_global:
                df = df[df['Fornecedor'].isin(sel_forn_global)]

            # Seleciona apenas as colunas que você determinou
            # Usamos errors='ignore' para evitar quebras se uma coluna falhar
            df_final = df[colunas_exigidas].sort_values("Compra sugerida", ascending=False)
            
            st.dataframe(
                df_final,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Preço de custo": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor Estoque Full": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor Estoque Fisico": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor total da compra sugerida": st.column_config.NumberColumn(format="R$ %.2f")
                }
            )
            
            # Totais por empresa em colunas para facilitar a leitura rápida
            c1, c2, c3 = st.columns(3)
            c1.metric(f"💰 Valoração Full {emp}", f"R$ {df_final['Valor Estoque Full'].sum():,.2f}")
            c2.metric(f"💰 Valoração Físico {emp}", f"R$ {df_final['Valor Estoque Fisico'].sum():,.2f}")
            c3.metric(f"🛒 Total Sugerido {emp}", f"R$ {df_final['Valor total da compra sugerida'].sum():,.2f}")
            st.divider()