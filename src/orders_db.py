# src/orders_db.py
import streamlit as st
from supabase import create_client
import pandas as pd
import datetime as dt

def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        return None

def listar_pedidos():
    """Baixa todos os pedidos e garante que as colunas existam."""
    supabase = init_supabase()
    if not supabase: return pd.DataFrame()
    
    try:
        # Busca dados brutos
        response = supabase.table("pedidos").select("*").execute()
        dados = response.data
        
        # Se não houver dados, retorna estrutura vazia correta
        if not dados:
            return pd.DataFrame(columns=["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status", "Obs", "Dados_Completos"])
            
        lista_formatada = []
        for p in dados:
            # Garante que campos opcionais tenham valor padrão
            obs_val = p.get("obs") or "" 
            
            lista_formatada.append({
                "ID": str(p.get("id", "")),
                "Data": str(p.get("data_emissao", "")),
                "Empresa": str(p.get("empresa", "")),
                "Fornecedor": str(p.get("fornecedor", "")),
                "Valor": float(p.get("valor_total", 0.0)),
                "Status": str(p.get("status", "Pendente")),
                "Obs": str(obs_val),
                "Dados_Completos": p.get("itens", [])
            })
            
        return pd.DataFrame(lista_formatada)
        
    except Exception as e:
        st.error(f"Erro ao listar pedidos: {e}")
        return pd.DataFrame()

def gerar_numero_oc(empresa):
    prefixo = "ALV" if empresa == "ALIVVIA" else "JCA"
    ano_atual = dt.date.today().year
    supabase = init_supabase()
    
    try:
        if supabase:
            res = supabase.table("pedidos").select("id", count="exact").ilike("id", f"OC-{prefixo}-{ano_atual}-%").execute()
            count = res.count + 1
            return f"OC-{prefixo}-{ano_atual}-{count:03d}"
    except: pass
    
    return f"OC-{prefixo}-{ano_atual}-{int(dt.datetime.now().timestamp())}"

def salvar_pedido(pedido_dict):
    supabase = init_supabase()
    if not supabase: return False
    
    try:
        dados_db = {
            "id": pedido_dict["id"],
            "empresa": pedido_dict["empresa"],
            "fornecedor": pedido_dict["fornecedor"],
            "data_emissao": pedido_dict["data_emissao"],
            "valor_total": pedido_dict["valor_total"],
            "status": pedido_dict["status"],
            "obs": pedido_dict["obs"],
            "itens": pedido_dict["itens"]
        }
        supabase.table("pedidos").upsert(dados_db).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

def atualizar_status(oc_id, novo_status):
    supabase = init_supabase()
    if supabase:
        supabase.table("pedidos").update({"status": novo_status}).eq("id", oc_id).execute()

def excluir_pedido_db(oc_id):
    supabase = init_supabase()
    if supabase:
        supabase.table("pedidos").delete().eq("id", oc_id).execute()