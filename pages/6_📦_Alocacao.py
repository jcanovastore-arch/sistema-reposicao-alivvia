import streamlit as st
import pandas as pd
from src import storage, logic, data, config

st.set_page_config(page_title="Alocação", layout="wide")
st.title("📦 Alocação de Compras (JCA vs ALIVVIA)")

st.info("Ferramenta para dividir uma compra grande (ex: 1000 unidades) baseado no histórico de vendas de cada empresa.")

# Precisamos dos dados calculados. Se não tiver, avisa.
if "res_ALIVVIA" not in st.session_state or "res_JCA" not in st.session_state:
    st.warning("Por favor, vá na aba 'Análise' e clique em CALCULAR para as duas empresas primeiro.")
    st.stop()

df_a = st.session_state["res_ALIVVIA"]
df_j = st.session_state["res_JCA"]

# Lista de SKUs comuns
skus_a = set(df_a["SKU"].unique())
skus_j = set(df_j["SKU"].unique())
todos_skus = sorted(list(skus_a.union(skus_j)))

sku_sel = st.selectbox("Selecione o Produto (Kit ou Peça):", [""] + todos_skus)

if sku_sel:
    # Dados Alivvia
    row_a = df_a[df_a["SKU"] == sku_sel]
    venda_a = row_a["Vendas_Total_60d"].sum() if not row_a.empty else 0
    est_a = row_a["Estoque_Total"].sum() if not row_a.empty else 0

    # Dados JCA
    row_j = df_j[df_j["SKU"] == sku_sel]
    venda_j = row_j["Vendas_Total_60d"].sum() if not row_j.empty else 0
    est_j = row_j["Estoque_Total"].sum() if not row_j.empty else 0

    # Totais
    total_vendas = venda_a + venda_j
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Vendas 60d ALIVVIA", int(venda_a))
    c2.metric("Vendas 60d JCA", int(venda_j))
    c3.metric("Vendas TOTAL", int(total_vendas))

    st.subheader("Simulador de Compra")
    qtd_compra = st.number_input("Quantidade a Comprar (ex: 1000)", value=0, step=10)

    if total_vendas > 0 and qtd_compra > 0:
        share_a = venda_a / total_vendas
        share_j = venda_j / total_vendas
        
        aloc_a = int(qtd_compra * share_a)
        aloc_j = int(qtd_compra * share_j)
        
        # Ajuste fino de arredondamento
        diff = qtd_compra - (aloc_a + aloc_j)
        if diff != 0: aloc_a += diff

        k1, k2 = st.columns(2)
        k1.success(f"Destinar para ALIVVIA: **{aloc_a}** peças ({share_a*100:.1f}%)")
        k2.warning(f"Destinar para JCA: **{aloc_j}** peças ({share_j*100:.1f}%)")
        
        if st.button("Enviar essa divisão para o Editor de OC"):
             st.session_state.pedido.append({"sku": sku_sel, "qtd": aloc_a, "valor": 0.0, "origem": "ALIVVIA (Aloc)"})
             st.session_state.pedido.append({"sku": sku_sel, "qtd": aloc_j, "valor": 0.0, "origem": "JCA (Aloc)"})
             st.success("Enviado!")
    elif qtd_compra > 0:
        st.error("Produto sem vendas nos últimos 60 dias. Impossível calcular alocação por histórico.")