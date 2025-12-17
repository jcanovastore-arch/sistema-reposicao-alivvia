# ... (mantenha as funções get_relatorio_full e read_file_from_storage iguais)

def calcular_reposicao(empresa, dias_cobertura, crescimento=0, lead_time=0):
    # 1. CARGA (CONGELADA)
    df_full_raw = get_relatorio_full(empresa)      
    df_ext_raw = get_vendas_externas(empresa)      
    df_fisico_raw = get_estoque_fisico(empresa)    
    dados_cat = st.session_state.get('catalogo_dados')
    
    if not dados_cat or 'catalogo' not in dados_cat:
        return None
    
    df_catalogo = dados_cat['catalogo'].copy()
    df_kits = dados_cat['kits'].copy()

    # --- PROTEÇÃO PARA O KEYERROR ---
    # Se a coluna 'sku' não estiver aqui, o merge falha. Garantimos que ela exista.
    if 'sku' not in df_catalogo.columns:
        st.error(f"Erro: Coluna SKU não identificada no Catálogo ({empresa}).")
        return None

    # (Mantenha todo o seu processamento de VENDAS FULL, SHOPEE e ESTOQUE FISICO exatamente como está)
    # ... [O código que você já tem de explosão de kits e separação de canais] ...

    # 5. MERGE FINAL (ONDE DAVA O ERRO)
    # Agora o merge está protegido pois o catalogo_loader garantiu a coluna 'sku'
    df_res = pd.merge(df_catalogo, v_full_map, on='sku', how='left')
    df_res = pd.merge(df_res, v_shopee_map, on='sku', how='left')
    df_res = pd.merge(df_res, est_map, on='sku', how='left')
    
    # ... (Mantenha o restante dos cálculos e o return rename exatamente como estão)