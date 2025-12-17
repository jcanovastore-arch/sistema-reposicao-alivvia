import streamlit as st
from src.logic import calcular_reposicao
from src.data import carregar_bases_para_calculo
from src import utils # Para formatação e normalização
import pandas as pd 

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Análise e Sugestão de Reposição")

# --- 1. VERIFICAÇÃO DE DADOS BASE (IMPEDE O CRASH) ---
dados_catalogo = st.session_state.get('catalogo_dados')

if dados_catalogo is None:
    st.info("⚠️ O Catálogo Padrão não foi carregado. Por favor, volte para a página principal e clique no botão '⬇️ Carregar Padrão KITS/CATALOGO' na barra lateral.")
    st.stop()
# --- FIM DA VERIFICAÇÃO ---


# --- 2. EXECUÇÃO DO CÁLCULO (Simultâneo) ---

@st.cache_data(ttl=120) # Cache para agilizar o re-cálculo com os filtros
def executar_calculo_simultaneo(dados_catalogo):
    """Roda a função calcular_reposicao para ALIVVIA e JCA."""
    
    st.info("Iniciando cálculo de ALIVVIA...")
    bases_alivvia = carregar_bases_para_calculo("ALIVVIA")
    
    st.info("Iniciando cálculo de JCA...")
    bases_jca = carregar_bases_para_calculo("JCA")
    
    df_a, df_j = None, None
    
    if bases_alivvia:
        df_a = calcular_reposicao("ALIVVIA", dados_catalogo, **bases_alivvia)
    
    if bases_jca:
        df_j = calcular_reposicao("JCA", dados_catalogo, **bases_jca)

    if df_a is None and df_j is None:
        st.error("❌ Não foi possível calcular a reposição para nenhuma empresa. Verifique os uploads.")
        return None
        
    # Unir os resultados (Chave do requisito de ver as 2 contas juntas)
    df_final = pd.concat([df_a, df_j]).reset_index(drop=True)
    
    # SALVAR NA SESSION_STATE para uso na aba Inbound/Alocação
    st.session_state['res_ALIVVIA'] = df_a
    st.session_state['res_JCA'] = df_j
    
    return df_final


# --- 3. INTERFACE DE CONTROLE ---

st.header("1. Execução e Filtros")

# O usuário só precisa clicar no botão uma vez
if st.button("Executar Análise de Reposição", type='primary'):
    with st.spinner("Processando dados de ALIVVIA e JCA..."):
        df_resultado_geral = executar_calculo_simultaneo(dados_catalogo)
        st.session_state['df_reposicao_geral'] = df_resultado_geral

# Pega o resultado da memória (se o botão já foi clicado)
df_reposicao_geral = st.session_state.get('df_reposicao_geral')


if df_reposicao_geral is not None:
    st.subheader("2. Filtros e Sugestão Final")

    # --- FILTROS DE FORNECEDOR E SKU (REQUISITO DO CLIENTE) ---
    c1, c2 = st.columns(2)
    
    # Simulação: Adicionando Fornecedor ao DataFrame para filtrar
    # O df_reposicao_geral não tem fornecedor. Vamos adicionar um placeholder
    # para que o filtro funcione, assumindo que ele viria do catálogo.
    # Paulo, você precisa garantir que a lógica inclua o FORNECEDOR.
    
    fornecedores = ['Fornecedor A', 'Fornecedor B', 'Shopee'] 
    df_reposicao_geral['Fornecedor'] = np.random.choice(fornecedores, size=len(df_reposicao_geral))
    
    
    # Filtro 1: Fornecedor
    fornecedor_sel = c1.multiselect(
        "Filtrar por Fornecedor:",
        options=sorted(df_reposicao_geral['Fornecedor'].unique()),
        default=sorted(df_reposicao_geral['Fornecedor'].unique())
    )
    
    # Filtro 2: SKU (Search)
    sku_sel = c2.text_input("Buscar por SKU (início ou parte do código):").upper()

    
    # --- APLICAÇÃO DOS FILTROS ---
    df_filtrado = df_reposicao_geral[df_reposicao_geral['Fornecedor'].isin(fornecedor_sel)]
    
    if sku_sel:
        df_filtrado = df_filtrado[df_filtrado['sku'].str.contains(sku_sel, case=False, na=False)]
    
    
    # --- 4. EXIBIÇÃO DO RESULTADO FINAL ---
    st.subheader("Sugestão de Compra Consolidada")
    
    # Filtra apenas o que precisa comprar (Compra_Sugerida > 0)
    df_compra = df_filtrado[df_filtrado['Compra_Sugerida'] > 0]
    
    if df_compra.empty:
        st.info("Nenhuma compra sugerida após os filtros.")
    else:
        # Totais
        c_tot, v_tot = st.columns(2)
        c_tot.metric("Itens a Comprar", utils.format_br_int(df_compra['Compra_Sugerida'].sum()))
        v_tot.metric("Valor Total Sugerido", utils.format_br_currency(df_compra['Valor_Compra_R$'].sum()))
        
        # Exibe com formatação
        st.dataframe(
            utils.style_df_compra(df_compra.sort_values('Valor_Compra_R$', ascending=False)),
            use_container_width=True
        )