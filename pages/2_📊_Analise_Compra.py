# --- ABA DE ALOCAÇÃO DE COMPRAS ---
st.divider()
st.header("📦 Ferramenta de Alocação de Compras")
st.info("Esta ferramenta divide uma quantidade total de compra entre as duas empresas com base na proporção de vendas de cada uma.")

with st.expander("Calcular Divisão de Pedido Grande", expanded=True):
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        sku_aloc = st.text_input("Digite o SKU para alocar", value=f_sku).strip().upper()
    with col_input2:
        qtd_total = st.number_input("Quantidade Total do Pedido (Ex: 1000)", min_value=0, value=0)

    if st.button("Executar Alocação de Pedido"):
        if not sku_aloc:
            st.warning("Por favor, digite um SKU.")
        elif qtd_total <= 0:
            st.warning("A quantidade total deve ser maior que zero.")
        else:
            # Busca vendas dos dois lados
            venda_alivvia = 0
            venda_jca = 0
            
            df_a = resultados.get("ALIVVIA")
            df_j = resultados.get("JCA")
            
            if df_a is not None and not df_a.empty:
                match = df_a[df_a['SKU'] == sku_aloc]
                if not match.empty:
                    venda_alivvia = match['Vendas full'].values[0] + match['vendas Shopee'].values[0]
            
            if df_j is not None and not df_j.empty:
                match = df_j[df_j['SKU'] == sku_aloc]
                if not match.empty:
                    venda_jca = match['Vendas full'].values[0] + match['vendas Shopee'].values[0]
            
            venda_total = venda_alivvia + venda_jca
            
            if venda_total == 0:
                st.error(f"O SKU {sku_aloc} não possui histórico de vendas em nenhuma das empresas.")
            else:
                # Cálculo da proporção
                prop_a = venda_alivvia / venda_total
                prop_j = venda_jca / venda_total
                
                aloc_a = int(np.floor(qtd_total * prop_a))
                aloc_j = qtd_total - aloc_a # JCA fica com o resto para fechar o total exato
                
                # Exibição do Resultado
                res_c1, res_c2, res_c3 = st.columns(3)
                res_c1.metric("Para ALIVVIA", f"{aloc_a} un", f"{prop_a:.1%}")
                res_c2.metric("Para JCA", f"{aloc_j} un", f"{prop_j:.1%}")
                res_c3.metric("Total Confirmado", f"{aloc_a + aloc_j} un")
                
                st.success(f"Cálculo baseado em: Vendas ALIVVIA ({venda_alivvia}) | Vendas JCA ({venda_jca})")