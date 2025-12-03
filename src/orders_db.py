# src/orders_db.py
# Conexão com Supabase (V8.0)

import streamlit as st
from supabase import create_client, Client
import pandas as pd
import datetime as dt

# Inicializa a conexão pegando os segredos do Streamlit Cloud
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error("Erro ao conectar no Supabase. Verifique os 'Secrets'.")
        return None

def listar_pedidos():
    """Baixa todos os pedidos do Supabase."""
    supabase = init_supabase()
    if not supabase: return pd.DataFrame()
    
    try:
        response = supabase.table("pedidos").select("*").execute()
        dados = response.data
        
        if not dados:
            return pd.DataFrame(columns=["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Dados_Completos"])
            
        lista_formatada = []
        for p in dados:
            lista_formatada.append({
                "ID": p["id"],
                "Data": p["data_emissao"],
                "Empresa": p["empresa"],
                "Fornecedor": p["fornecedor"],
                "Valor": float(p["valor_total"]),
                "Status": p["status"],
                "Dados_Completos": p # Guarda o objeto todo para o PDF
            })
        
        # Retorna ordenado por Data (mais novo primeiro)
        df = pd.DataFrame(lista_formatada)
        return df.sort_values(by="Data", ascending=False)
        
    except Exception as e:
        st.error(f"Erro ao listar: {e}")
        return pd.DataFrame()

def gerar_numero_oc(empresa):
    """Gera o próximo ID baseado na contagem do banco."""
    supabase = init_supabase()
    if not supabase: return "ERRO"
    
    ano_atual = dt.datetime.now().strftime("%Y")
    prefixo = "ALV" if empresa == "ALIVVIA" else "JCA"
    
    # Conta quantos pedidos dessa empresa existem neste ano
    # (Lógica simplificada: conta tudo que contem o prefixo e ano)
    filtro = f"OC-{prefixo}-{ano_atual}"
    
    # Pega todos os IDs para calcular localmente o maximo (mais seguro)
    try:
        response = supabase.table("pedidos").select("id").ilike("id", f"{filtro}%").execute()
        existentes = response.data
        novo_num = len(existentes) + 1
        return f"OC-{prefixo}-{ano_atual}-{novo_num:03d}"
    except:
        return f"OC-{prefixo}-{ano_atual}-001"

def salvar_pedido(pedido_dict):
    """Envia o pedido para o Supabase."""
    supabase = init_supabase()
    if not supabase: return
    
    try:
        # Prepara o JSON para o formato do banco
        dados_db = {
            "id": pedido_dict["id"],
            "empresa": pedido_dict["empresa"],
            "fornecedor": pedido_dict["fornecedor"],
            "data_emissao": pedido_dict["data_emissao"],
            "valor_total": pedido_dict["valor_total"],
            "status": pedido_dict["status"],
            "obs": pedido_dict["obs"],
            "itens": pedido_dict["itens"] # O Supabase aceita JSON direto
        }
        
        supabase.table("pedidos").upsert(dados_db).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

def atualizar_status(oc_id, novo_status):
    """Atualiza apenas o status."""
    supabase = init_supabase()
    if not supabase: return
    try:
        supabase.table("pedidos").update({"status": novo_status}).eq("id", oc_id).execute()
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")

def excluir_pedido_db(oc_id):
    """Remove pedido do banco."""
    supabase = init_supabase()
    if not supabase: return
    try:
        supabase.table("pedidos").delete().eq("id", oc_id).execute()
    except Exception as e:
        st.error(f"Erro ao excluir: {e}")