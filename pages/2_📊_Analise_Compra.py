import streamlit as st
from src.logic import calcular_reposicao
from src.data import carregar_bases_para_calculo
from src import utils
import pandas as pd 
import numpy as np

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Painel de Reposição Integrado")

# --- BARRA LATERAL (CONFIGURAÇÃO) ---
with st.sidebar:
    st.header("⚙️ Parâmetros de Compra")
    dias_horizonte = st.number_input("Dias de Cobertura", min_value=15, value=45, step=5, help="Para quantos dias de venda você quer ter estoque?")
    crescimento = st.number_input("Crescimento Esperado (%)", min_value=0.0, value=0.0, step=5.0, help="Adiciona uma gordura percentual na venda média")
    lead_time = st.number_input("Lead Time (Dias)", min_value=0, value=0, step=1, help="Dias que o fornecedor demora para entregar (margem de segurança)")
    
    st.divider()
    st.info(f"Cálculo: (Venda Diária x {dias_horizonte + lead_time} dias) + {crescimento}%")
    
    if st.button("🔄 Recalcular Tudo", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --- VERIFICAÇÃO ---
dados_catalogo = st.session_state.get('catalogo_dados')
if dados_catalogo is None:
    st.warning("⚠️ Catálogo não carregado. Vá na Home e carregue o padrão.")
    st.stop()

# --- CÁLCULO GLOBAL (AS DUAS EMPRESAS) ---
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

resultados = calcular_tudo(dias_horizonte, crescimento, lead_time)

if not resultados:
    st.error("Não foi possível calcular. Verifique se fez os uploads.")
    st.stop()

# --- FILTRO INTELIGENTE UNIFICADO ---
# Pega todos os fornecedores das duas empresas
forns_a = resultados.get("ALIVVIA", pd.DataFrame())
forns_j = resultados.get("JCA", pd.DataFrame())
lista_a = forns_a['Fornecedor'].dropna().unique() if not forns_a.empty else []
lista_j = forns_j['Fornecedor'].dropna().unique() if not forns_j.empty else []
todos_fornecedores = sorted(list(set(lista_a) | set(lista_j)))

st.markdown("### 🔎 Filtros Globais")
c_filtro1, c_filtro2 = st.columns([1, 1])
sel_fornecedor = c_filtro1.multiselect("Selecione Fornecedor(es) (Filtra ambas as lojas):", options=todos_fornecedores)
busca_sku = c_filtro2.text_input("Buscar SKU:").upper()

# --- FUNÇÃO DE EXIBIÇÃO ---
def exibir_painel_empresa(nome_empresa, df_original, filtro_forn, filtro_sku):
    st.markdown(f"---")
    st.subheader(f"🏢 {nome_empresa}")
    
    # Aplica Filtros
    df = df_original.copy()
    if filtro_forn:
        df = df[df['Fornecedor'].isin(filtro_forn)]
    if filtro_sku:
        df = df[df['SKU'].str.contains(filtro_sku, na=False)]
        
    if df.empty:
        st.info("Sem dados para os filtros selecionados.")
        return

    # --- MÉTRICAS DE TOPO (O QUE VOCÊ PEDIU) ---
    # Estoque Full (Un e R$) + Sugestão de Compra
    estoque_full_un = df['Estoque_Full'].sum()
    estoque_full_rs = (df['Estoque_Full'] * df['Preco_Custo']).sum()
    sugestao_total = df['Valor_Compra'].sum()
    pecas_comprar = df['Compra_Sugerida'].sum()
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Estoque Full (Un)", f"{int(estoque_full_un):,}".replace(",", "."))
    k2.metric("Estoque Full (R$)", utils.format_br_currency(estoque_full_rs))
    k3.metric("Sugestão Compra (R$)", utils.format_br_currency(sugestao_total))
    k4.metric("Peças a Comprar", f"{int(pecas_comprar):,}".replace(",", "."))
    
    # --- TABELA DETALHADA ---
    # Colunas específicas pedidas: Vendas Full e Vendas Shopee separadas
    colunas = [
        'SKU', 'Fornecedor', 
        'Estoque_Fisico', 'Estoque_Full', 
        'Vendas_Full_60d', 'Vendas_Shopee_60d', 'Vendas_Via_Kits', # <--- SEPARADO
        'Venda_Diaria',
        'Compra_Sugerida', 'Valor_Compra', 'Preco_Custo'
    ]
    
    # Filtra apenas o que tem movimento ou estoque para não poluir
    df_view = df[(df['Estoque_Total'] > 0) | (df['Compra_Sugerida'] > 0) | (df['Vendas_Total_Global_60d'] > 0)]
    
    # Ordena: Primeiro o que tem que comprar (maior valor), depois fornecedor
    df_view = df_view.sort_values(['Valor_Compra', 'Fornecedor'], ascending=[False, True])
    
    st.dataframe(
        df_view[colunas],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Vendas_Full_60d": st.column_config.NumberColumn("Vendas ML (60d)", help="Vendas vindas do arquivo Full"),
            "Vendas_Shopee_60d": st.column_config.NumberColumn("Vendas Shopee (60d)", help="Vendas vindas do arquivo Externo"),
            "Vendas_Via_Kits": st.column_config.NumberColumn("Vendas Kits", help="Vendas calculadas da explosão de kits"),
            "Venda_Diaria": st.column_config.NumberColumn("Média/Dia", format="%.1f"),
            "Estoque_Full": st.column_config.NumberColumn("Estoque Full", format="%d"),
            "Estoque_Fisico": st.column_config.NumberColumn("Estoque Físico", format="%d"),
            "Compra_Sugerida": st.column_config.NumberColumn("SUGESTÃO COMPRA", format="%d"),
            "Valor_Compra": st.column_config.NumberColumn("Valor Total", format="R$ %.2f"),
            "Preco_Custo": st.column_config.NumberColumn("Custo Unit.", format="R$ %.2f"),
        }
    )

# --- RENDERIZAÇÃO ---
if "ALIVVIA" in resultados:
    exibir_painel_empresa("ALIVVIA", resultados["ALIVVIA"], sel_fornecedor, busca_sku)

if "JCA" in resultados:
    exibir_painel_empresa("JCA", resultados["JCA"], sel_fornecedor, busca_sku)