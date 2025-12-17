# ... (mantenha as funções de leitura get_relatorio_full, etc., iguais)

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # --- LEITURA CONGELADA ---
    df_full = get_relatorio_full(empresa)      
    df_ext = get_vendas_externas(empresa)      
    df_fisico = get_estoque_fisico(empresa)    
    
    dados_cat = st.session_state.get('catalogo_dados')
    if not dados_cat or 'catalogo' not in dados_cat:
        return None
    
    df_catalogo = dados_cat['catalogo'].copy()

    # --- PROTEÇÃO ADICIONAL ---
    if 'sku' not in df_catalogo.columns:
        st.error(f"Coluna SKU não encontrada no catálogo da {empresa}")
        return None

    df_catalogo['sku'] = df_catalogo['sku'].apply(utils.norm_sku)

    # ... (Mantenha TODO o resto do seu código de merge e cálculo exatamente como está)
    # A lógica de compra, Shopee e Full continua congelada aqui abaixo.