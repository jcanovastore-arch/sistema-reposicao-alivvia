import streamlit as st
import pandas as pd
import time
from src import orders_db, utils

st.set_page_config(page_title="Gestão OCs", layout="wide")
st.title("🗂️ Histórico e Gestão de Pedidos")

# --- 1. Listagem ---
st.write("Abaixo estão todas as Ordens de Compra salvas no banco de dados.")

# Chama a função do módulo orders_db
df_history = orders_db.listar_pedidos()

if df_history.empty:
    st.info("Nenhum pedido encontrado no histórico.")
    st.stop()

# Mostra tabela resumida
st.dataframe(
    df_history[["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Obs"]], 
    use_container_width=True
)

st.divider()

# --- 2. Painel de Controle (Atualizar/Excluir) ---
c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("Gerenciar Pedido")
    # Selectbox com os IDs das OCs
    lista_ids = df_history["ID"].unique()
    sel_oc = st.selectbox("Selecione a OC:", lista_ids)

    if sel_oc:
        # Pega status atual
        status_atual = df_history[df_history["ID"] == sel_oc]["Status"].iloc[0]
        st.caption(f"Status Atual: **{status_atual}**")
        
        # Mudar Status
        novo_status = st.selectbox("Novo Status:", ["Pendente", "Aprovado", "Enviado", "Recebido", "Cancelado"])
        
        if st.button("💾 Atualizar Status"):
            orders_db.atualizar_status(sel_oc, novo_status)
            st.success("Status atualizado com sucesso!")
            time.sleep(1)
            st.rerun()

        st.write("---")
        # Excluir (Opcional, mas útil)
        if st.button("🗑️ Excluir OC Definitivamente", type="primary"):
            # Função para excluir (precisa existir no orders_db, vou simular ou usar update)
            # Como orders_db.py padrão só tem update, vamos marcar como Cancelado ou excluir se tiver a função
            orders_db.atualizar_status(sel_oc, "EXCLUIDO") 
            st.warning("OC marcada como Excluída/Cancelada.")
            time.sleep(1)
            st.rerun()

with c2:
    st.subheader(f"Detalhes dos Itens: {sel_oc}")
    if sel_oc:
        # Pega a linha completa do dataframe
        row = df_history[df_history["ID"] == sel_oc].iloc[0]
        itens_raw = row.get("Dados_Completos")
        
        if isinstance(itens_raw, list) and len(itens_raw) > 0:
            df_itens = pd.DataFrame(itens_raw)
            
            # Formatações visuais
            if "valor_unit" in df_itens.columns:
                df_itens["valor_unit"] = df_itens["valor_unit"].apply(lambda x: utils.format_br_currency(float(x)))
            
            st.dataframe(df_itens, use_container_width=True)
            
            # Totalizador
            total_val = row["Valor"]
            # Tenta converter string de moeda de volta pra float só pra exibir no metric, ou usa o valor bruto se tiver
            st.metric("Valor Total deste Pedido", row["Valor"])
        else:
            st.warning("Não há itens detalhados registrados para este pedido.")