import streamlit as st
import pandas as pd
import time
from src import orders_db

st.set_page_config(page_title="Editor OC", layout="wide")
st.title("📝 Editor de Ordem de Compra")

if not st.session_state.pedido:
    st.info("Carrinho vazio.")
    st.stop()

df = pd.DataFrame(st.session_state.pedido)

# Edição
edited = st.data_editor(
    df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "valor": st.column_config.NumberColumn("Valor Unit.", format="R$ %.2f"),
        "total": None
    }
)

# Atualiza memória
st.session_state.pedido = edited.to_dict("records")

# Total
df_calc = pd.DataFrame(st.session_state.pedido)
total = (df_calc["qtd"] * df_calc["valor"]).sum() if not df_calc.empty else 0
st.metric("TOTAL OC", f"R$ {total:,.2f}")

c1, c2, c3 = st.columns(3)
forn = c1.text_input("Fornecedor")
emp = c2.selectbox("Empresa", ["ALIVVIA", "JCA"])
obs = c3.text_input("Obs")

if st.button("💾 SALVAR PEDIDO", type="primary"):
    if not forn: st.error("Falta Fornecedor")
    else:
        nid = orders_db.gerar_numero_oc(emp)
        dados = {
            "id": nid, "empresa": emp, "fornecedor": forn, 
            "valor_total": total, "status": "Pendente", "obs": obs,
            "itens": st.session_state.pedido,
            "data_emissao": str(pd.Timestamp.now().date())
        }
        if orders_db.salvar_pedido(dados):
            st.success(f"OC {nid} Gerada!")
            st.session_state.pedido = []
            time.sleep(2); st.rerun()

if st.button("Limpar Carrinho"):
    st.session_state.pedido = []
    st.rerun()