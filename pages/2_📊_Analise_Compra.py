import streamlit as st
import pandas as pd
import numpy as np
from src.logic import calcular_reposicao

# Configuração da página deve ser a PRIMEIRA coisa
st.set_page_config(page_title="Análise de Compra", layout="wide")

st.title("📊 Painel de Compras e Alocação")

# Verifica se os dados foram carregados na Home
if not st.session_state.get('catalogo_carregado'):
    st.error("⚠️ O Catálogo não foi carregado. Volte à Home e clique em 'Carregar Padrão'.")
    st.stop()

# --- SIDEBAR: PARÂMETROS ---
with st.sidebar:
    st.header("⚙️ Parâmetros de Estoque")
    dias_h = st.number_input("Dias Cobertura", min_value=15, value=45, step=5)
    cresc = st.number_input("Crescimento %", min_value=0.0, value=0.0, step=5.0)
    lead = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1)
    
    st.divider()
    st.header("🔍 Filtros Globais")
    f_sku = st.text_input("Filtrar SKU (Global)").strip().upper()
    
    if st.button("🔄 Recalcular Tudo", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Função de cálculo com Cache para performance
@st.cache_data
def carregar_resultados(d, c, l):
    return {
        "ALIVVIA": calcular_reposicao("ALIVVIA", d, c, l),
        "JCA": calcular_reposicao("JCA", d, c, l)
    }

# Executa o cálculo
resultados = carregar_resultados(dias_h, cresc, lead)

# --- ABA 1: ANÁLISE DETALHADA ---
tab_analise, tab_alocacao = st.tabs(["📋 Análise por Empresa", "📦 Calculadora de Alocação"])

with tab_analise:
    colunas_exigidas = [
        "SKU", "Fornecedor", "Preço de custo", 
        "Vendas full", "vendas Shopee", 
        "Estoque full (Un)", "Estoque fisico (Un)", 
        "Compra sugerida", "Valor total da compra sugerida"
    ]

    for emp in ["ALIVVIA", "JCA"]:
        df = resultados.get(emp)
        if df is not None and not df.empty:
            st.subheader(f"🏢 {emp}")
            if f_sku:
                df = df[df['SKU'].str.contains(f_sku, na=False)]
            
            st.dataframe(df[colunas_exigidas], use_container_width=True, hide_index=True)
        else:
            st.warning(f"Sem dados processados para {emp}.")

# --- ABA 2: ALOCAÇÃO DE COMPRAS (Sua nova ferramenta) ---
with tab_alocacao:
    st.info("Divida um pedido grande entre as empresas baseado na performance real de vendas.")
    
    col_al1, col_al2 = st.columns(2)
    with col_al1:
        sku_aloc = st.text_input("SKU para Alocação", value=f_sku).strip().upper()
    with col_al2:
        qtd_total = st.number_input("Quantidade Total a Comprar", min_value=0, value=1000)

    if st.button("CALCULAR DIVISÃO"):
        venda_a = 0
        venda_j = 0
        
        # Busca vendas nos resultados já calculados
        for emp, df in resultados.items():
            if df is not None and not df.empty:
                row = df[df['SKU'] == sku_aloc]
                if not row.empty:
                    v = row['Vendas full'].values[0] + row['vendas Shopee'].values[0]
                    if emp == "ALIVVIA": venda_a = v
                    else: venda_j = v

        total_vendas = venda_a + venda_j

        if total_vendas > 0:
            p_a = venda_a / total_vendas
            p_j = venda_j / total_vendas
            
            # Alocação proporcional
            aloc_a = int(np.floor(qtd_total * p_a))
            aloc_j = qtd_total - aloc_a
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Alocar para ALIVVIA", f"{aloc_a} un", f"{p_a:.1%}")
            c2.metric("Alocar para JCA", f"{aloc_j} un", f"{p_j:.1%}")
            c3.metric("Total", f"{qtd_total} un")
            
            
            
            st.success(f"Cálculo feito: ALIVVIA vendeu {venda_a} e JCA vendeu {venda_j} nos últimos 60 dias.")
        else:
            st.error("Não foram encontradas vendas deste SKU para calcular a proporção.")