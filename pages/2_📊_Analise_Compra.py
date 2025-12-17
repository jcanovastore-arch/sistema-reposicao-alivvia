import streamlit as st
from src.logic import calcular_reposicao
from src.data import carregar_bases_para_calculo
from src import utils # Para formatação
import pandas as pd 
import numpy as np

st.set_page_config(page_title="Análise de Compra", layout="wide")
st.title("📊 Análise e Sugestão de Reposição")

# --- 1. VERIFICAÇÃO DE DADOS BASE (IMPEDE O CRASH E FAZ O BOTÃO APARECER) ---
dados_catalogo = st.session_state.get('catalogo_dados')

if dados_catalogo is None:
    st.info("⚠️ O Catálogo Padrão não foi carregado. Por favor, volte para a página principal e clique no botão '⬇️ Carregar Padrão KITS/CATALOGO' na barra lateral.")
    st.stop()
# --- FIM DA VERIFICAÇÃO ---


# --- 2. FUNÇÃO DE EXECUÇÃO SIMULTÂNEA (Com correção da chamada) ---

@st.cache_data(ttl=120) 
def executar_calculo_simultaneo(dados_catalogo):
    """Roda a função calcular_reposicao para ALIVVIA e JCA."""
    
    bases_alivvia = carregar_bases_para_calculo("ALIVVIA")
    bases_jca = carregar_bases_para_calculo("JCA")
    
    df_a, df_j = None, None
    
    if bases_alivvia:
        st.info("Iniciando cálculo de ALIVVIA...")
        # --- CORREÇÃO DA CHAMADA (PASSANDO O DICIONÁRIO COMPLETO) ---
        df_a = calcular_reposicao("ALIVVIA", bases_alivvia) 
    
    if bases_jca:
        st.info("Iniciando cálculo de JCA...")
        # --- CORREÇÃO DA CHAMADA (PASSANDO O DICIONÁRIO COMPLETO) ---
        df_j = calcular_reposicao("JCA", bases_jca)

    # ... (Resto do código para unificar e salvar o resultado)
    df_calculados = []
    if df_a is not None: df_calculados.append(df_a)
    if df_j is not None: df_calculados.append(df_j)

    if not df_calculados:
        st.error("❌ Não foi possível gerar a sugestão. Verifique os uploads e o Catálogo.")
        return None
        
    df_final = pd.concat(df_calculados).reset_index(drop=True)
    
    st.session_state['res_ALIVVIA'] = df_a
    st.session_state['res_JCA'] = df_j
    st.session_state['df_reposicao_geral'] = df_final # Salva para o uso na interface
    
    return df_final


# --- 3. INTERFACE DE CONTROLE ---

st.header("1. Execução e Filtros")

# O usuário só precisa clicar no botão uma vez
if st.button("Executar Análise de Reposição", type='primary'):
    # Limpa cache para garantir que os dados do Supabase sejam atualizados
    st.cache_data.clear() 
    with st.spinner("Processando dados de ALIVVIA e JCA..."):
        executar_calculo_simultaneo(dados_catalogo)
        st.success("Cálculo concluído. Use os filtros abaixo.")

# Pega o resultado da memória (se o botão já foi clicado)
df_reposicao_geral = st.session_state.get('df_reposicao_geral')

if df_reposicao_geral is not None:
    st.subheader("2. Filtros e Sugestão Final")

    # --- FILTROS DE FORNECEDOR E SKU (REQUISITO) ---
    c1, c2 = st.columns(2)
    
    # Simulação de Fornecedor (Você precisa garantir que o fornecedor venha do seu merge)
    fornecedores = ['Fornecedor A', 'Fornecedor B', 'Shopee'] 
    df_reposicao_geral['Fornecedor'] = np.random.choice(fornecedores, size=len(df_reposicao_geral)) # PLACEHOLDER
    
    
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
    
    df_compra = df_filtrado[df_filtrado['Compra_Sugerida'] > 0]
    
    if df_compra.empty:
        st.info("Nenhuma compra sugerida após os filtros.")
    else:
        # Totais
        c_tot, v_tot = st.columns(2)
        c_tot.metric("Itens a Comprar", f"{df_compra['Compra_Sugerida'].sum():,.0f}".replace(',', '.'))
        v_tot.metric("Valor Total Sugerido", f"R$ {df_compra['Valor_Compra_R$'].sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        
        # Exibe com formatação (Assumindo que utils.style_df_compra existe)
        st.dataframe(
            df_compra.sort_values('Valor_Compra_R$', ascending=False),
            use_container_width=True
        )