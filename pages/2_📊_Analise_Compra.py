import streamlit as st
import pandas as pd
import numpy as np
from src.logic import calcular_reposicao

# Configuração da página
st.set_page_config(page_title="Análise de Compra", layout="wide")

st.title("📊 Painel de Compras e Alocação")

# Verifica se os dados foram carregados na Home
if not st.session_state.get('catalogo_dados'):
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
    f_sku = st.text_input("Filtrar SKU na Tabela").strip().upper()
    
    if st.button("🔄 Recalcular Tudo", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Função de cálculo com Cache
@st.cache_data
def carregar_resultados(d, c, l):
    return {
        "ALIVVIA": calcular_reposicao("ALIVVIA", d, c, l),
        "JCA": calcular_reposicao("JCA", d, c, l)
    }

resultados = carregar_resultados(dias_h, cresc, lead)

# --- CRIAÇÃO DAS ABAS ---
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
            df_view = df.copy()
            if f_sku:
                df_view = df_view[df_view['SKU'].str.contains(f_sku, na=False)]
            
            st.dataframe(df_view[colunas_exigidas], use_container_width=True, hide_index=True)
        else:
            st.warning(f"Sem dados processados para {emp}.")

# --- ABA 2: ALOCAÇÃO DE COMPRAS (PUXANDO DO CATÁLOGO) ---
with tab_alocacao:
    st.header("📦 Divisão Proporcional de Compra")
    st.info("Selecione um SKU oficial do seu catálogo para dividir o pedido entre ALIVVIA e JCA.")
    
    # Puxa a lista oficial de SKUs do catálogo carregado
    lista_skus_oficial = sorted(st.session_state['catalogo_dados']['catalogo']['sku'].unique())

    col_al1, col_al2 = st.columns(2)
    with col_al1:
        # Seleção segura: O usuário só escolhe o que existe
        sku_selecionado = st.selectbox("Selecione o SKU do Catálogo", options=lista_skus_oficial, index=0)
    with col_al2:
        qtd_total = st.number_input("Quantidade Total da NF (Ex: 1000)", min_value=0, value=1000)

    if st.button("CALCULAR DIVISÃO"):
        venda_a = 0
        venda_j = 0
        
        # Busca performance real nos cálculos já feitos
        for emp, df in resultados.items():
            if df is not None and not df.empty:
                row = df[df['SKU'] == sku_selecionado]
                if not row.empty:
                    # Soma vendas Full e Shopee (já explodidas se for o caso)
                    v = row['Vendas full'].values[0] + row['vendas Shopee'].values[0]
                    if emp == "ALIVVIA": venda_a = v
                    else: venda_j = v

        total_vendas_grupo = venda_a + venda_j

        if total_vendas_grupo > 0:
            p_a = venda_a / total_vendas_grupo
            p_j = venda_j / total_vendas_grupo
            
            # Alocação
            aloc_a = int(np.floor(qtd_total * p_a))
            aloc_j = qtd_total - aloc_a # Ajuste para não sobrar nem faltar 1 un por arredondamento
            
            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("ALIVVIA (Enviar)", f"{aloc_a} un", f"{p_a:.1%}")
            c2.metric("JCA (Enviar)", f"{aloc_j} un", f"{p_j:.1%}")
            c3.metric("Total Pedido", f"{qtd_total} un")
            
            
            
            st.success(f"Histórico (Últimos 60 dias): ALIVVIA vendeu {venda_a} un | JCA vendeu {venda_j} un.")
        else:
            st.warning(f"O SKU {sku_selecionado} não possui histórico de vendas em nenhuma empresa para gerar proporção.")