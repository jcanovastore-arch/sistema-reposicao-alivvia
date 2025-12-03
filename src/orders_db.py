# src/orders_db.py
import os
import json
import pandas as pd
import datetime as dt
from .config import STORAGE_DIR

# Caminho do banco de dados local (Futuramente mudaremos isso para Google Sheets)
DB_FILE = os.path.join(STORAGE_DIR, "banco_pedidos.json")

def _load_db():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def _save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def gerar_numero_oc(empresa: str) -> str:
    """Gera ID sequencial: OC-ALV-2023-001"""
    db = _load_db()
    ano = dt.datetime.now().year
    prefixo = "ALV" if empresa == "ALIVVIA" else "JCA"
    
    # Filtra OCs dessa empresa e desse ano
    ocs_ano = [p for p in db if p['empresa'] == empresa and str(ano) in p['id']]
    seq = len(ocs_ano) + 1
    return f"OC-{prefixo}-{ano}-{seq:03d}"

def salvar_pedido(pedido_dict: dict):
    """
    Estrutura esperada do dict:
    {
        "id": "OC-ALV-2025-001",
        "empresa": "ALIVVIA",
        "fornecedor": "ABC",
        "data_emissao": "2025-12-03",
        "status": "PENDENTE",
        "obs": "...",
        "itens": [
            {"sku": "A", "qtd": 10, "valor": 5.0}, ...
        ],
        "valor_total": 500.00
    }
    """
    db = _load_db()
    # Verifica se já existe (edição) ou cria novo
    db.append(pedido_dict)
    _save_db(db)

def listar_pedidos():
    db = _load_db()
    # Retorna como DataFrame para facilitar exibição
    if not db:
        return pd.DataFrame(columns=["ID", "Data", "Empresa", "Fornecedor", "Valor", "Status"])
    
    resumo = []
    for p in db:
        resumo.append({
            "ID": p["id"],
            "Data": p["data_emissao"],
            "Empresa": p["empresa"],
            "Fornecedor": p["fornecedor"],
            "Valor": p["valor_total"],
            "Status": p.get("status", "PENDENTE"),
            "Dados_Completos": p # Guarda o objeto todo escondido caso precise
        })
    return pd.DataFrame(resumo).sort_values("Data", ascending=False)

def atualizar_status(id_oc, novo_status):
    db = _load_db()
    for p in db:
        if p["id"] == id_oc:
            p["status"] = novo_status
            break
    _save_db(db)