import streamlit as st
import pandas as pd
import re
from src import logic, utils

st.set_page_config(page_title="Inbound", layout="wide")
st.title("🚛 Conferência de Inbound")

st.info("Esta ferramenta cruza o arquivo de envio (Inbound) com o Estoque Físico para identificar o que precisa ser reposto imediatamente.")

# Seleção da Empresa
emp_target = st.radio("Para qual empresa é este envio?", ["ALIVVIA", "JCA"], horizontal=True)

# Verificação de segurança: O usuário já calculou o estoque na aba 2?
if f"res_{emp_target}" not in st.session_state:
    st.warning(f"⚠️ Você precisa ir na aba 'Análise de Compra' e clicar em CALCULAR para a {emp_target} antes de usar o Inbound. Precisamos dos dados de Estoque Físico e Preço que estão lá.")
    st.stop()

# Upload do Arquivo de Inbound
up_in = st.file_uploader("Upload Arquivo Inbound (Excel ou PDF)", type=["xlsx", "csv", "pdf"])

if up_in:
    data_in = []
    
    # --- 1. Leitura do Arquivo (Excel ou PDF) ---
    if up_in.name.lower().endswith(".pdf"):
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(up_in.getvalue())) as pdf:
            txt = "".join([p.extract_text() or "" for p in pdf.pages])
            # Regex para capturar SKU no PDF
            matches = re.findall(r'SKU:?\s*([\w\-\/\+\.\&]+)', txt, re.IGNORECASE)
            # PDF geralmente não tem a quantidade fácil de ler, assumimos 1 ou pedimos excel
            for m in matches: 
                data_in.append({"SKU": m.upper().strip(), "Qtd_Envio": 0}) 
        st.warning("⚠️ Leitura de PDF é limitada (não captura quantidades com precisão). Para resultados exatos, use o Excel/CSV do Inbound.")
    
    else:
        # Leitura Inteligente do Excel
        df_i = logic.smart_read_excel_csv(up_in.getvalue())
        
        # Procura colunas chave
        c_prod = next((c for c in df_i.columns if "PRODUTO" in str(c).upper()), None)
        c_qtd = next((c for c in df_i.columns if "UNIDADES" in str(c).upper()), None)
        
        if c_prod and c_qtd:
            regex = re.compile(r'SKU:?\s*([\w\-\/\+\.\&]+)', re.IGNORECASE)
            for _, r in df_i.iterrows():
                m = regex.search(str(r[c_prod]))
                if m: 
                    val_q = utils.br_to_float(r[c_qtd])
                    data_in.append({"SKU": m.group(1).upper().strip(), "Qtd_Envio": val_q})
        else:
            st.error("Não encontrei as colunas 'PRODUTO' e 'UNIDADES' no arquivo.")

    # --- 2. Processamento e Cruzamento ---
    if data_in:
        # Agrupa SKUs duplicados no arquivo de entrada
        df_inb = pd.DataFrame(data_in).groupby("SKU", as_index=False)["Qtd_Envio"].sum()
        
        # Pega os dados da aba de Análise (Estoque Físico e Preço)
        base_analise = st.session_state[f"res_{emp_target}"].copy()
        
        # Faz o cruzamento (Merge)
        merged = df_inb.merge(base_analise[["SKU", "Estoque_Fisico", "Preco"]], on="SKU", how="left")
        
        # Cálculos Finais
        merged["Estoque_Fisico"] = merged["Estoque_Fisico"].fillna(0)
        merged["Preco"] = merged["Preco"].fillna(0)
        
        # O que falta = O que vou enviar - O que tenho no físico
        merged["Faltam_Comprar"] = (merged["Qtd_Envio"] - merged["Estoque_Fisico"]).clip(lower=0)
        merged["Custo_Falta"] = merged["Faltam_Comprar"] * merged["Preco"]
        
        # --- 3. Exibição ---
        k1, k2 = st.columns(2)
        k1.metric("Peças Faltantes (Total)", utils.format_br_int(merged["Faltam_Comprar"].sum()))
        k2.metric("Custo Reposição Imediata", utils.format_br_currency(merged["Custo_Falta"].sum()))
        
        st.dataframe(merged, use_container_width=True)
        
        # --- 4. Botão de Ação ---
        if st.button("🛒 Adicionar Faltantes ao Editor de OC"):
            count = 0
            # Recupera carrinho atual
            if "pedido" not in st.session_state: st.session_state.pedido = []
            
            # Lista SKUs que já estão no carrinho para não duplicar
            skus_no_carrinho = [item["sku"] for item in st.session_state.pedido]
            
            for _, row in merged[merged["Faltam_Comprar"] > 0].iterrows():
                if row["SKU"] not in skus_no_carrinho:
                    st.session_state.pedido.append({
                        "sku": row["SKU"],
                        "qtd": int(row["Faltam_Comprar"]),
                        "valor_unit": float(row["Preco"]),
                        "origem": f"INBOUND_{emp_target}",
                        "total": row["Faltam_Comprar"] * row["Preco"]
                    })
                    count += 1
            
            if count > 0:
                st.success(f"{count} itens enviados para a aba Editor de OC!")
            else:
                st.warning("Nenhum item novo adicionado (ou itens já estavam no carrinho).")