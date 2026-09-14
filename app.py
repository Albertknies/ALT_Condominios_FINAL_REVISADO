from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, session, abort
import html
import io
import json
import logging
import re
import secrets
import shutil
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from waitress import serve

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "alt.db"
BACKUPS = BASE / "backups"
PDFS = BASE / "PDFs"
PORT = int(os.environ.get("ALT_PORT", "47891"))
DB.parent.mkdir(exist_ok=True)
BACKUPS.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("ALT_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

logging.basicConfig(level=logging.INFO, format="[ALT] %(levelname)s: %(message)s")

# Campos simples armazenados diretamente no cadastro.
FIELDS = [
    "nome", "cnpj", "unidades",
    "sindicoTipo", "sindico", "cpfSindico", "unSindico", "telSindico", "emailSindico",
    "empresaSindico", "cnpjEmpresaSindico", "responsavelSindico", "telResponsavelSindico",
    "ataEleicao", "ultAGO", "inicioMandato", "fimMandato",
    "conselho", "qtdConselheiros",
    "banco", "agencia", "conta",
    "conv", "convFis", "reg", "regFis", "admFis",
    "ppci", "validPpci", "ppciFis", "ext", "recarga", "extFis", "brig", "qtdBrig",
    "cxData", "cxFis", "dedData", "dedFis",
    "seg", "segEmpresa", "segData", "segFis", "corretorResponsavelSeg", "contatoCorretorSeg",
    "luz", "agua", "gas", "gasTipo", "codCad", "empresaGas", "codigoGasOutra",
    "quemLimpeza", "empresaLimpeza", "freqLimpeza", "cargaLimpeza", "limpFis",
    "seguranca", "empresaSeg", "segFis2",
    "juridico", "nomeJuridico", "percCobranca", "jurFis",
    "mercadinho", "nomeMerc", "respMerc", "contatoMerc", "repasseMerc", "periodoMerc", "dataMerc", "mercFis",
    "obs"
]
YES_NO = {"Sim", "Não"}
SINDICO_TIPOS = {"Morador", "Profissional"}
GAS_TIPOS = {"Ultragás", "Administração", "Outra"}


@contextmanager
def conn():
    database = app.config.get("DATABASE", DB)
    c = sqlite3.connect(database, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS condominios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            atualizado_em TEXT NOT NULL,
            dados_json TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_condominios_nome ON condominios(nome COLLATE NOCASE)")
        c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_auditoria_created_at ON auditoria(created_at)")
        c.execute("""CREATE TABLE IF NOT EXISTS financeiro_receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condominio_id INTEGER,
            grupo TEXT NOT NULL DEFAULT 'ALT',
            categoria TEXT,
            valor REAL NOT NULL,
            data_pagamento TEXT,
            mes_referencia TEXT NOT NULL,
            metodo_pagamento TEXT,
            numero_documento TEXT,
            status TEXT DEFAULT 'Recebido',
            observacao TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(condominio_id) REFERENCES condominios(id) ON DELETE CASCADE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS financeiro_despesas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            categoria TEXT,
            fornecedor TEXT,
            valor REAL NOT NULL,
            vencimento TEXT NOT NULL,
            mes_referencia TEXT NOT NULL,
            parcelas INTEGER NOT NULL DEFAULT 1,
            metodo_pagamento TEXT,
            numero_documento TEXT,
            status TEXT DEFAULT 'Pendente',
            observacao TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS financeiro_categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'receita',
            descricao TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_financeiro_receitas_mes ON financeiro_receitas(mes_referencia)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_financeiro_despesas_mes ON financeiro_despesas(mes_referencia)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_financeiro_categorias_tipo ON financeiro_categorias(tipo)")
        admin = c.execute("SELECT 1 FROM usuarios WHERE username = ?", ("admin",)).fetchone()
        if admin is None:
            c.execute(
                "INSERT INTO usuarios(username, password_hash, role, created_at) VALUES(?,?,?,?)",
                ("admin", generate_password_hash("admin"), "admin", datetime.now().isoformat(timespec="seconds")),
            )
        c.commit()

    ensure_finance_schema()


def ensure_finance_schema():
    with conn() as c:
        finance_tables = {
            "financeiro_receitas": {
                "condominio_id": "INTEGER",
                "grupo": "TEXT DEFAULT 'ALT'",
                "categoria": "TEXT",
                "data_pagamento": "TEXT",
                "metodo_pagamento": "TEXT",
                "numero_documento": "TEXT",
                "status": "TEXT DEFAULT 'Recebido'",
            },
            "financeiro_despesas": {
                "categoria": "TEXT",
                "fornecedor": "TEXT",
                "metodo_pagamento": "TEXT",
                "numero_documento": "TEXT",
                "status": "TEXT DEFAULT 'Pendente'",
            },
            "financeiro_categorias": {
                "nome": "TEXT",
                "tipo": "TEXT DEFAULT 'receita'",
                "descricao": "TEXT",
            },
        }
        for table_name, columns in finance_tables.items():
            columns_existing = {row[1] for row in c.execute(f"PRAGMA table_info({table_name})").fetchall()}
            for col_name, col_definition in columns.items():
                if col_name not in columns_existing:
                    c.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}")
        c.commit()


def clean(v, limit=5000):
    if v is None:
        return ""
    return str(v).strip()[:limit]


def parse_int(value, minimum=0, maximum=10000, blank=""):
    value = clean(value)
    if not value:
        return blank
    if not value.isdigit():
        raise ValueError("valor inteiro inválido")
    n = int(value)
    if n < minimum or n > maximum:
        raise ValueError("valor inteiro fora do limite")
    return str(n)


def valid_date(value):
    value = clean(value)
    if not value:
        return ""
    datetime.strptime(value, "%Y-%m-%d")
    return value


def valid_choice(value, choices):
    value = clean(value)
    if value and value not in choices:
        raise ValueError("opção inválida")
    return value


def parse_date_value(value):
    value = clean(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def classify_due_days(days_left, warning_days=30):
    if days_left <= 0:
        return "red"
    if days_left <= warning_days:
        return "yellow"
    return "green"


def parse_monetary(value):
    if value is None:
        raise ValueError("Informe o valor.")
    try:
        amount = Decimal(str(value).replace(".", "").replace(",", ".")) if isinstance(value, str) else Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Valor financeiro inválido.")
    if amount <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    return float(amount)


def month_add(month_text, months):
    month_text = clean(month_text)
    if not month_text:
        month_text = datetime.now().strftime("%Y-%m")
    try:
        year, month = map(int, month_text.split("-"))
    except ValueError:
        raise ValueError("Use o mês no formato YYYY-MM.")
    total_months = (year * 12 + month - 1) + months
    new_year, new_month = divmod(total_months, 12)
    return f"{new_year:04d}-{(new_month + 1):02d}"


def month_date(month_text, day):
    month_text = clean(month_text) or datetime.now().strftime("%Y-%m")
    try:
        year, month = map(int, month_text.split("-"))
    except ValueError as exc:
        raise ValueError("Use o mês no formato YYYY-MM.") from exc
    last_day = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day if month == 12 else (date(year, month + 1, 1) - timedelta(days=1)).day
    target_day = min(int(day), last_day) if day else last_day
    return date(year, month, target_day)


def get_finance_summary(month_text):
    month_text = clean(month_text) or datetime.now().strftime("%Y-%m")
    with conn() as c:
        receita_total = c.execute("SELECT COALESCE(SUM(valor), 0) FROM financeiro_receitas WHERE mes_referencia = ?", (month_text,)).fetchone()[0] or 0
        despesa_total = c.execute("SELECT COALESCE(SUM(valor), 0) FROM financeiro_despesas WHERE mes_referencia = ?", (month_text,)).fetchone()[0] or 0
        receitas = c.execute("SELECT r.id, r.condominio_id, c.nome AS condominio, r.grupo, r.categoria, r.valor, r.data_pagamento, r.metodo_pagamento, r.numero_documento, r.status, r.mes_referencia, r.observacao, r.created_at FROM financeiro_receitas r LEFT JOIN condominios c ON c.id = r.condominio_id WHERE r.mes_referencia = ? ORDER BY r.created_at DESC", (month_text,)).fetchall()
        despesas = c.execute("SELECT * FROM financeiro_despesas WHERE mes_referencia = ? ORDER BY vencimento DESC, id DESC", (month_text,)).fetchall()
    receitas_formatted = []
    for row in receitas:
        item = dict(row)
        item["nome_exibicao"] = item.get("condominio") or item.get("grupo") or "ALT"
        item["tipo_label"] = "ALT" if item.get("grupo") == "ALT" else "Condomínio"
        receitas_formatted.append(item)
    return {
        "mes": month_text,
        "receita": float(receita_total),
        "despesa": float(despesa_total),
        "saldo": float(receita_total) - float(despesa_total),
        "receitas": receitas_formatted,
        "despesas": [dict(row) for row in despesas],
    }


def get_finance_categorias(tipo=None):
    with conn() as c:
        if tipo:
            rows = c.execute(
                "SELECT * FROM financeiro_categorias WHERE tipo = ? ORDER BY nome COLLATE NOCASE",
                (tipo,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM financeiro_categorias ORDER BY tipo, nome COLLATE NOCASE").fetchall()
    return [dict(row) for row in rows]


def get_finance_categoria_summary(month_text=None):
    month_text = clean(month_text) or datetime.now().strftime("%Y-%m")
    with conn() as c:
        receitas = c.execute(
            "SELECT categoria AS nome, COALESCE(SUM(valor), 0) AS total FROM financeiro_receitas WHERE mes_referencia = ? AND categoria IS NOT NULL AND categoria <> '' GROUP BY categoria ORDER BY total DESC",
            (month_text,),
        ).fetchall()
        despesas = c.execute(
            "SELECT categoria AS nome, COALESCE(SUM(valor), 0) AS total FROM financeiro_despesas WHERE mes_referencia = ? AND categoria IS NOT NULL AND categoria <> '' GROUP BY categoria ORDER BY total DESC",
            (month_text,),
        ).fetchall()

    resumo = []
    for row in receitas:
        resumo.append({"nome": row["nome"], "tipo": "receita", "total": float(row["total"] or 0)})
    for row in despesas:
        resumo.append({"nome": row["nome"], "tipo": "despesa", "total": float(row["total"] or 0)})

    resumo.sort(key=lambda item: (-item["total"], item["nome"].lower()))
    return resumo


def get_finance_categorias_page_data(month_text=None):
    month_text = clean(month_text) or datetime.now().strftime("%Y-%m")
    return {
        "mes": month_text,
        "receitas": get_finance_categorias("receita"),
        "despesas": get_finance_categorias("despesa"),
        "resumo": get_finance_categoria_summary(month_text),
    }


def describe_days_left(days_left):
    if days_left == 0:
        return "vence hoje"
    if days_left < 0:
        return f"vencido há {abs(days_left)} dia{'s' if abs(days_left) != 1 else ''}"
    return f"vence em {days_left} dia{'s' if days_left != 1 else ''}"


def get_issue_due_date(label, raw_value):
    due_date = parse_date_value(raw_value)
    if not due_date:
        return None

    if label in {"Validade do PPCI", "Mandato do síndico"}:
        return due_date
    if label == "Dedetização":
        return due_date + timedelta(days=180)
    return due_date + timedelta(days=365)


def describe_due_date(due_date, days_left):
    if not due_date:
        return ""
    txt = due_date.strftime("%d/%m/%Y")
    if days_left < 0:
        return f"Vencido em {txt}"
    if days_left == 0:
        return f"Vence hoje ({txt})"
    return f"Válido até {txt}"


def get_condominio_alert_status(d):
    if not isinstance(d, dict):
        d = {}

    checks = [
        ("Validade do PPCI", d.get("validPpci"), 30),
        ("Limpeza da caixa d'água", d.get("cxData"), 30),
        ("Mandato do síndico", d.get("fimMandato"), 30),
        ("Recarga de extintor", d.get("recarga"), 30),
        ("Seguro predial", d.get("segData"), 30),
        ("Dedetização", d.get("dedData"), 30),
    ]

    issues = []
    level = "green"
    for label, raw_value, warning_days in checks:
        if not raw_value:
            continue
        due_date = get_issue_due_date(label, raw_value)
        if not due_date:
            continue
        days_left = (due_date - datetime.now().date()).days
        status = classify_due_days(days_left, warning_days)
        if status == "red":
            level = "red"
        elif status == "yellow" and level == "green":
            level = "yellow"
        issues.append({
            "label": label,
            "date": due_date.isoformat(),
            "date_label": describe_due_date(due_date, days_left),
            "status": status,
            "days_left": days_left,
            "days_left_label": describe_days_left(days_left),
        })

    return {
        "level": level,
        "issues": issues,
        "red_count": sum(1 for issue in issues if issue["status"] == "red"),
        "yellow_count": sum(1 for issue in issues if issue["status"] == "yellow"),
        "green_count": sum(1 for issue in issues if issue["status"] == "green"),
    }


def normalize_address(d):
    # Novo formato estruturado; migra automaticamente cadastros antigos que tinham endereço em texto.
    addr = d.get("endereco")
    if isinstance(addr, dict):
        return {k: clean(addr.get(k, ""), 300) for k in ("rua", "numero", "complemento", "bairro", "cidade", "estado", "cep")}
    old = clean(addr, 1000)
    return {"rua": old, "numero": "", "complemento": "", "bairro": "", "cidade": "", "estado": "", "cep": ""}


def normalize_conselheiros(d):
    items = d.get("conselheiros")
    if isinstance(items, list):
        out = []
        for x in items[:20]:
            if isinstance(x, dict):
                out.append({"nome": clean(x.get("nome", ""), 300), "unidade": clean(x.get("unidade", ""), 100)})
        return out
    # Migração dos 3 campos do formato anterior.
    out = []
    for i in range(1, 4):
        nome = clean(d.get(f"c{i}nome", ""), 300)
        unidade = clean(d.get(f"c{i}un", ""), 100)
        if nome or unidade:
            out.append({"nome": nome, "unidade": unidade})
    return out


def normalize_brigadistas(d):
    items = d.get("brigadistas")
    if not isinstance(items, list):
        return []
    return [{"nome": clean(x.get("nome", ""), 300), "unidade": clean(x.get("unidade", ""), 100)}
            for x in items[:100] if isinstance(x, dict)]


def strip_digits(value):
    return re.sub(r"\D", "", clean(value))


def collect_form(form):
    d = {f: clean(form.get(f, "")) for f in FIELDS}

    for key in ("cnpj", "cpfSindico", "cnpjEmpresaSindico", "telSindico", "telResponsavelSindico"):
        d[key] = strip_digits(d[key])
    d["endereco"] = {k: strip_digits(form.get(f"endereco_{k}", "")) if k == "cep" else clean(form.get(f"endereco_{k}", ""), 300)
                     for k in ("rua", "numero", "complemento", "bairro", "cidade", "estado", "cep")}
    d["endereco"]["estado"] = clean(d["endereco"].get("estado", ""), 2).upper()

    for key in ("conselho", "conv", "convFis", "reg", "regFis", "ppci", "ppciFis", "ext", "extFis", "brig",
                "cxFis", "dedFis", "seg", "segFis", "limpFis", "seguranca", "segFis2", "juridico", "jurFis",
                "mercadinho", "mercFis", "admFis", "gas"):
        d[key] = valid_choice(d[key], YES_NO)
    d["sindicoTipo"] = valid_choice(d["sindicoTipo"], SINDICO_TIPOS)
    d["gasTipo"] = valid_choice(d["gasTipo"], GAS_TIPOS)

    d["unidades"] = parse_int(d["unidades"], 1, 100000)
    d["qtdBrig"] = parse_int(d["qtdBrig"], 0, 100, blank="")
    d["qtdConselheiros"] = parse_int(d["qtdConselheiros"], 0, 20, blank="")

    for key in ("ataEleicao", "ultAGO", "inicioMandato", "fimMandato", "validPpci", "recarga", "cxData", "dedData", "segData"):
        d[key] = valid_date(d[key])

    if d["emailSindico"] and (len(d["emailSindico"]) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", d["emailSindico"])):
        raise ValueError("e-mail do síndico inválido")

    # Conselho: quantidade controla a lista. Nome e unidade são os únicos dados solicitados.
    qtd_c = int(d["qtdConselheiros"] or 0) if d["conselho"] == "Sim" else 0
    d["qtdConselheiros"] = str(qtd_c) if d["conselho"] == "Sim" else ""
    d["conselheiros"] = []
    for i in range(qtd_c):
        d["conselheiros"].append({
            "nome": clean(form.get(f"cons{i}nome", ""), 300),
            "unidade": clean(form.get(f"cons{i}unidade", ""), 100),
        })
    if d["conselho"] != "Sim":
        d["qtdConselheiros"] = ""

    # Síndico: morador ou profissional.
    if d["sindicoTipo"] == "Morador":
        for key in ("empresaSindico", "cnpjEmpresaSindico", "responsavelSindico", "telResponsavelSindico"):
            d[key] = ""
    elif d["sindicoTipo"] == "Profissional":
        for key in ("cpfSindico", "unSindico", "emailSindico"):
            d[key] = ""
        if not d["responsavelSindico"]:
            raise ValueError("informe o síndico responsável da empresa")
        if not d["telResponsavelSindico"]:
            raise ValueError("informe o telefone do síndico responsável")

    if d["conv"] != "Sim": d["convFis"] = ""
    if d["reg"] != "Sim": d["regFis"] = ""
    if d["ppci"] != "Sim": d["validPpci"] = d["ppciFis"] = ""
    if d["ext"] != "Sim": d["recarga"] = d["extFis"] = ""
    if d["brig"] != "Sim": d["qtdBrig"] = ""

    qtd_b = int(d["qtdBrig"] or 0) if d["brig"] == "Sim" else 0
    d["brigadistas"] = []
    for i in range(qtd_b):
        d["brigadistas"].append({"nome": clean(form.get(f"brig{i}nome", ""), 300), "unidade": clean(form.get(f"brig{i}un", ""), 100)})

    if d["seg"] != "Sim": d["segEmpresa"] = d["segData"] = d["segFis"] = ""
    if d["seguranca"] != "Sim": d["empresaSeg"] = d["segFis2"] = ""
    if d["juridico"] != "Sim": d["nomeJuridico"] = d["percCobranca"] = d["jurFis"] = ""
    if d["mercadinho"] != "Sim":
        for key in ("nomeMerc", "respMerc", "contatoMerc", "repasseMerc", "periodoMerc", "dataMerc", "mercFis"): d[key] = ""

    # Gás: fornecedor/gestor + campos mínimos conforme escolha.
    if d["gas"] != "Sim":
        d["gasTipo"] = d["codCad"] = d["empresaGas"] = d["codigoGasOutra"] = ""
    elif d["gasTipo"] == "Ultragás":
        d["empresaGas"] = d["codigoGasOutra"] = ""
    elif d["gasTipo"] == "Outra":
        if not d["empresaGas"]: raise ValueError("informe a empresa do gás")
        if not d["codigoGasOutra"]: raise ValueError("informe o código para cadastro do gás")
        d["codCad"] = ""
    elif d["gasTipo"] == "Administração":
        d["codCad"] = d["empresaGas"] = d["codigoGasOutra"] = ""
    else:
        d["gasTipo"] = d["codCad"] = d["empresaGas"] = d["codigoGasOutra"] = ""

    return d


def auto_backup():
    if not DB.exists(): return
    try:
        target = BACKUPS / f"ALT-auto-{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
        shutil.copy2(DB, target)
        files = sorted(BACKUPS.glob("ALT-auto-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[15:]: old.unlink(missing_ok=True)
    except OSError:
        logging.exception("Não foi possível criar o backup automático")


def save_condominio(d, cid=None):
    now = datetime.now().isoformat(timespec="seconds")
    payload = json.dumps(d, ensure_ascii=False)
    with conn() as c:
        if cid is not None:
            cur = c.execute("UPDATE condominios SET nome=?, atualizado_em=?, dados_json=? WHERE id=?", (d["nome"], now, payload, cid))
            if cur.rowcount != 1:
                return None
        else:
            cur = c.execute("INSERT INTO condominios(nome, atualizado_em, dados_json) VALUES(?,?,?)", (d["nome"], now, payload))
            cid = cur.lastrowid
        c.commit()
    return cid


def load_data(row):
    try:
        d = json.loads(row["dados_json"])
        if not isinstance(d, dict): return {}
    except (json.JSONDecodeError, TypeError):
        return {}
    # Compatibilidade/migração preguiçosa.
    d["endereco"] = normalize_address(d)
    d["conselheiros"] = normalize_conselheiros(d)
    d["brigadistas"] = normalize_brigadistas(d)
    if "qtdConselheiros" not in d and d.get("conselheiros"): d["qtdConselheiros"] = str(len(d["conselheiros"]))
    return d


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32); session["csrf_token"] = token
    return token


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with conn() as c:
        row = c.execute("SELECT id, username, role, password_hash FROM usuarios WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def _create_expense_installments(nome, valor, vencimento, parcelas, mes_referencia, observacao):
    parcelas = max(1, int(parcelas or 1))
    vencimento_date = datetime.strptime(vencimento, "%Y-%m-%d").date()
    created = []
    month_ref = clean(mes_referencia) or datetime.now().strftime("%Y-%m")
    for idx in range(parcelas):
        ref_month = month_add(month_ref, idx)
        due_day = vencimento_date.day
        due_date = month_date(ref_month, due_day)
        created.append({
            "nome": clean(nome),
            "valor": float(valor),
            "vencimento": due_date.isoformat(),
            "mes_referencia": ref_month,
            "parcelas": parcelas,
            "observacao": clean(observacao),
        })
    return created


def log_audit(action, details="", username=None):
    username = username or (current_user() or {}).get("username")
    with conn() as c:
        c.execute(
            "INSERT INTO auditoria(username, action, details, created_at) VALUES(?,?,?,?)",
            (username, action, details, datetime.now().isoformat(timespec="seconds")),
        )
        c.commit()


def create_user(username, password, role="normal", password_confirm=None):
    username = clean(username).strip()
    if not username:
        raise ValueError("Informe o nome de usuário.")
    if password is None or len(str(password)) < 4:
        raise ValueError("A senha deve ter pelo menos 4 caracteres.")
    if password_confirm is not None and str(password) != str(password_confirm):
        raise ValueError("As senhas não conferem.")
    role = clean(role).lower() if role else "normal"
    if role not in {"admin", "normal", "financeiro"}:
        raise ValueError("Perfil inválido.")
    with conn() as c:
        existing = c.execute("SELECT id FROM usuarios WHERE username = ?", (username,)).fetchone()
        if existing is not None:
            raise ValueError("Usuário já existe.")
        c.execute(
            "INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)",
            (username, generate_password_hash(str(password)), role),
        )
        c.commit()
    return username


def update_user_profile(user_id, username, password=None, password_confirm=None):
    username = clean(username).strip()
    if not username:
        raise ValueError("Informe o nome de usuário.")

    with conn() as c:
        current = c.execute("SELECT id, username, password_hash, role FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if current is None:
            raise ValueError("Usuário não encontrado.")

        existing = c.execute(
            "SELECT id FROM usuarios WHERE username = ? AND id != ?",
            (username, user_id),
        ).fetchone()
        if existing is not None:
            raise ValueError("Usuário já existe.")

        if password is not None and str(password) != "":
            if len(str(password)) < 4:
                raise ValueError("A senha deve ter pelo menos 4 caracteres.")
            if password_confirm is not None and str(password) != str(password_confirm):
                raise ValueError("As senhas não conferem.")
            c.execute(
                "UPDATE usuarios SET username = ?, password_hash = ? WHERE id = ?",
                (username, generate_password_hash(str(password)), user_id),
            )
        else:
            c.execute("UPDATE usuarios SET username = ? WHERE id = ?", (username, user_id))
        c.commit()

    return username


def authenticate_user(username, password):
    username = clean(username).strip()
    if not username:
        return None
    with conn() as c:
        row = c.execute("SELECT * FROM usuarios WHERE username = ?", (username,)).fetchone()
    if row and check_password_hash(row["password_hash"], password or ""):
        return dict(row)
    return None


def safe_next_url(value):
    """Retorna apenas destinos internos para evitar redirecionamento externo."""
    value = clean(value, 2000)
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return None
    return value


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user.get("role") != "admin":
            flash("Este perfil não tem acesso administrativo.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def finance_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user.get("role") not in {"admin", "financeiro"}:
            flash("Este perfil não tem acesso financeiro.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_helpers(): return {"csrf_token": csrf_token, "current_user": current_user}


@app.before_request
def protect_posts():
    if request.path.startswith("/static"):
        return None
    if request.endpoint in {"login", "logout", "health"}:
        return None
    if not current_user():
        if request.path not in {"/login", "/logout"}:
            return redirect(url_for("login", next=request.path))
        return None
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, description="Sessão de segurança inválida. Atualize a página e tente novamente.")


@app.get("/health")
def health(): return jsonify(ok=True, app="ALT Gestão de Condomínios")


@app.get("/usuarios")
@login_required
@admin_required
def usuarios():
    mes = clean(request.args.get("mes", ""))
    if mes:
        try:
            datetime.strptime(mes, "%Y-%m")
        except ValueError:
            mes = ""
    if not mes:
        mes = datetime.now().strftime("%Y-%m")

    with conn() as c:
        rows = c.execute("SELECT id, username, role, created_at FROM usuarios ORDER BY username COLLATE NOCASE").fetchall()
        audit_rows = c.execute(
            "SELECT username, action, details, created_at FROM auditoria WHERE strftime('%Y-%m', created_at) = ? ORDER BY id DESC LIMIT 20",
            (mes,),
        ).fetchall()

    return render_template(
        "usuarios.html",
        usuarios=[dict(r) for r in rows],
        recent_entries=[dict(r) for r in audit_rows],
        filtro_mes=mes,
    )


@app.get("/auditoria")
@login_required
@admin_required
def auditoria():
    usuario = clean(request.args.get("usuario", ""))
    acao = clean(request.args.get("acao", ""))
    data = clean(request.args.get("data", ""))
    mes = clean(request.args.get("mes", ""))
    if mes:
        try:
            datetime.strptime(mes, "%Y-%m")
        except ValueError:
            mes = ""
    if not mes:
        mes = datetime.now().strftime("%Y-%m")

    query = "SELECT username, action, details, created_at FROM auditoria WHERE 1=1"
    params = []
    if usuario:
        query += " AND username = ?"
        params.append(usuario)
    if acao:
        query += " AND action = ?"
        params.append(acao)
    if data:
        query += " AND DATE(created_at) = ?"
        params.append(data)
    if mes:
        query += " AND strftime('%Y-%m', created_at) = ?"
        params.append(mes)
    query += " ORDER BY id DESC LIMIT 200"

    with conn() as c:
        rows = c.execute(query, params).fetchall()

    entries = [dict(r) for r in rows]
    with conn() as c:
        usuarios = [row[0] for row in c.execute("SELECT DISTINCT username FROM auditoria WHERE username IS NOT NULL ORDER BY username COLLATE NOCASE").fetchall()]
        acoes = [row[0] for row in c.execute("SELECT DISTINCT action FROM auditoria ORDER BY action COLLATE NOCASE").fetchall()]

    return render_template("auditoria.html", entries=entries, usuarios=usuarios, acoes=acoes, filtro_usuario=usuario, filtro_acao=acao, filtro_data=data, filtro_mes=mes)


@app.get("/auditoria/exportar-pdf")
@login_required
@admin_required
def exportar_auditoria_pdf():
    mes = clean(request.args.get("mes", "")) or datetime.now().strftime("%Y-%m")
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        abort(400, description="Mês inválido. Use o formato YYYY-MM.")

    usuario = clean(request.args.get("usuario", ""))
    acao = clean(request.args.get("acao", ""))

    query = "SELECT username, action, details, created_at FROM auditoria WHERE strftime('%Y-%m', created_at) = ?"
    params = [mes]
    if usuario:
        query += " AND username = ?"
        params.append(usuario)
    if acao:
        query += " AND action = ?"
        params.append(acao)
    query += " ORDER BY created_at DESC"

    with conn() as c:
        rows = c.execute(query, params).fetchall()

    folder = PDFS / "auditoria" / mes
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"auditoria-{mes}-{datetime.now():%Y-%m-%d_%H-%M-%S}.pdf"
    path = folder / filename

    story = [
        Paragraph("ALT GESTÃO DE CONDOMÍNIOS", styles["TitleALT"]),
        Paragraph("RELATÓRIO MENSAL DE AUDITORIA", styles["SubALT"]),
        Paragraph(f"<b>Mês:</b> {mes}", styles["Value"]),
        Spacer(1, 12),
    ]

    if not rows:
        story.append(Paragraph("Nenhuma ação registrada neste mês para os filtros selecionados.", styles["Value"]))
    else:
        table_data = [[
            Paragraph("Data", styles["Label"]),
            Paragraph("Usuário", styles["Label"]),
            Paragraph("Ação", styles["Label"]),
            Paragraph("Detalhes", styles["Label"]),
        ]]
        for row in rows:
            table_data.append([
                Paragraph(pdf_value(row["created_at"]), styles["Value"]),
                Paragraph(pdf_value(row["username"] or "Sistema"), styles["Value"]),
                Paragraph(pdf_value(row["action"]), styles["Value"]),
                Paragraph(pdf_value(row["details"] or "-"), styles["Value"]),
            ])
        table = Table(table_data, colWidths=[90, 100, 120, 220])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F1F6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=38)
    doc.build(story)
    log_audit("exportar_pdf_auditoria", f"Relatório mensal da auditoria {mes} exportado por {session.get('username')}", session.get('username'))
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.post("/usuarios/criar")
@login_required
@admin_required
def criar_usuario():
    try:
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        role = request.form.get("role", "normal")
        create_user(username, password, role, password_confirm)
        log_audit("criar_usuario", f"Usuário {username} criado por {session.get('username')}", session.get('username'))
        flash(f"Usuário {username} criado com sucesso.", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("usuarios"))


@app.post("/usuarios/<int:user_id>/editar")
@login_required
@admin_required
def editar_usuario(user_id):
    with conn() as c:
        row = c.execute("SELECT id, username FROM usuarios WHERE id=?", (user_id,)).fetchone()
    if row is None:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("usuarios"))

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")

    try:
        new_username = update_user_profile(user_id, username, password=password if str(password).strip() else None, password_confirm=password_confirm)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("usuarios"))

    if current_user() and current_user().get("id") == user_id:
        session["username"] = new_username

    log_audit("editar_usuario", f"Usuário {row['username']} atualizado por {session.get('username')}", session.get('username'))
    flash(f"Usuário {new_username} atualizado com sucesso.", "ok")
    return redirect(url_for("usuarios"))


@app.post("/usuarios/<int:user_id>/resetar-senha")
@login_required
@admin_required
def reset_senha_usuario(user_id):
    with conn() as c:
        row = c.execute("SELECT username FROM usuarios WHERE id=?", (user_id,)).fetchone()
    if row is None:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("usuarios"))

    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")
    if len(new_password or "") < 4:
        flash("A nova senha deve ter pelo menos 4 caracteres.", "error")
        return redirect(url_for("usuarios"))
    if str(new_password) != str(new_password_confirm):
        flash("A confirmação da nova senha não confere.", "error")
        return redirect(url_for("usuarios"))

    with conn() as c:
        c.execute("UPDATE usuarios SET password_hash=? WHERE id=?", (generate_password_hash(new_password), user_id))
        c.commit()
    log_audit("resetar_senha", f"Senha do usuário {row['username']} redefinida por {session.get('username')}", session.get('username'))
    flash(f"Senha redefinida para o usuário {row['username']}.", "ok")
    return redirect(url_for("usuarios"))


@app.post("/usuarios/<int:user_id>/excluir")
@login_required
@admin_required
def excluir_usuario(user_id):
    with conn() as c:
        row = c.execute("SELECT username FROM usuarios WHERE id=?", (user_id,)).fetchone()
        if row is None:
            flash("Usuário não encontrado.", "error")
            return redirect(url_for("usuarios"))
        if row["username"] == "admin":
            flash("O usuário administrador principal não pode ser removido.", "error")
            return redirect(url_for("usuarios"))
        c.execute("DELETE FROM usuarios WHERE id=?", (user_id,))
        c.commit()
    log_audit("excluir_usuario", f"Usuário {row['username']} removido por {session.get('username')}", session.get('username'))
    flash(f"Usuário {row['username']} excluído.", "ok")
    return redirect(url_for("usuarios"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = authenticate_user(username, password)
        if not user:
            flash("Credenciais inválidas.", "error")
            return render_template("login.html", next=request.args.get("next") or url_for("index"))
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        log_audit("login", f"Usuário {user['username']} entrou no sistema.", user["username"])
        requested_next = request.form.get("next") or request.args.get("next")
        next_page = safe_next_url(requested_next) or url_for("index")
        return redirect(next_page)
    return render_template("login.html", next=request.args.get("next") or url_for("index"))


@app.route("/logout")
def logout():
    username = session.get("username")
    session.clear()
    if username:
        log_audit("logout", f"Usuário {username} saiu do sistema.", username)
    return redirect(url_for("login"))


@app.get("/importar")
@login_required
def importar():
    return render_template("importar.html")


@app.route("/")
@app.route("/home")
@app.route("/inicio")
@login_required
def index():
    with conn() as c:
        rows = c.execute("SELECT * FROM condominios ORDER BY nome COLLATE NOCASE, id").fetchall()

    total = len(rows)
    profissionais = 0
    moradores = 0
    items = []

    for row in rows:
        d = {}
        try:
            d = load_data(row)
        except Exception:
            d = {}

        if d.get("sindicoTipo") == "Profissional":
            profissionais += 1
        elif d.get("sindicoTipo") == "Morador":
            moradores += 1

        nome = clean(d.get("nome") or row["nome"], 200)
        responsavel = clean(d.get("responsavelSindico") or d.get("sindico") or d.get("empresaSindico") or "", 200)
        empresa = clean(d.get("empresaSindico") or d.get("nomeJuridico") or "", 200)
        endereco = address_text(d.get("endereco"))
        search_text = " ".join(filter(None, [
            nome, responsavel, empresa, d.get("sindicoTipo", ""), d.get("cnpj", ""),
            d.get("emailSindico", ""), d.get("telSindico", ""),
            d.get("telResponsavelSindico", ""), endereco,
        ])).lower()
        status = get_condominio_alert_status(d)

        items.append({
            "id": row["id"],
            "nome": nome,
            "atualizado_em": row["atualizado_em"],
            "search_text": search_text,
            "status": status["level"],
            "issues": status["issues"],
            "issue_labels": [f"{issue['label']} ({format_date(issue['date'])})" for issue in status["issues"]],
        })

    summary = {
        "red": sum(1 for item in items if item["status"] == "red"),
        "yellow": sum(1 for item in items if item["status"] == "yellow"),
        "green": sum(1 for item in items if item["status"] == "green"),
    }

    return render_template(
        "index.html",
        items=items,
        total=total,
        profissionais=profissionais,
        moradores=moradores,
        sem_sindico=max(0, total - profissionais - moradores),
        alert_summary=summary,
    )


@app.route("/novo")
@login_required
def novo(): return render_template("form.html", d={}, cid=None, today=datetime.now().strftime("%Y-%m-%d"))
@app.get("/carteiras")
@login_required
def carteiras():
    wallet_map = {}
    moradores = []

    with conn() as c:
        rows = c.execute(
            "SELECT * FROM condominios ORDER BY nome COLLATE NOCASE"
        ).fetchall()

    for row in rows:
        d = load_data(row)
        tipo = d.get("sindicoTipo") or "Sem tipo"

        if tipo == "Profissional":
            nome_sindico = clean(d.get("responsavelSindico"), 200) or clean(d.get("empresaSindico"), 200) or "Responsável não informado"
            tipo_label = "Carteira profissional"
            key = (tipo_label, nome_sindico)
        elif tipo == "Morador":
            nome_sindico = clean(d.get("sindico"), 200) or "Síndico morador"
            tipo_label = "Carteira morador"
            key = (tipo_label, nome_sindico)
        else:
            nome_sindico = "Não informado"
            tipo_label = "Sem tipo"
            key = (tipo_label, nome_sindico)

        wallet = wallet_map.setdefault(key, {
            "tipo": tipo_label,
            "sindico": nome_sindico,
            "condominios": [],
            "search": " ".join(filter(None, [tipo_label, nome_sindico, row["nome"]])).lower(),
        })

        wallet["condominios"].append({
            "id": row["id"],
            "nome": row["nome"],
            "empresa": d.get("empresaSindico", ""),
            "telefone": d.get("telResponsavelSindico", "") or d.get("telSindico", ""),
            "responsavel": d.get("responsavelSindico", "") or d.get("sindico", ""),
        })

        if tipo == "Morador":
            moradores.append({
                "id": row["id"],
                "nome": row["nome"],
                "sindico": d.get("sindico", "")
            })

    wallets = sorted(wallet_map.values(), key=lambda item: (item["tipo"].lower(), item["sindico"].lower()))
    total_profissionais = sum(1 for w in wallets if w["tipo"] == "Carteira profissional")

    return render_template(
        "carteiras.html",
        wallets=wallets,
        moradores=moradores,
        total=len(rows),
        total_profissionais=total_profissionais,
    )


@app.get("/financeiro")
@login_required
@finance_required
def financeiro():
    mes = clean(request.args.get("mes", datetime.now().strftime("%Y-%m"))) or datetime.now().strftime("%Y-%m")
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        mes = datetime.now().strftime("%Y-%m")

    with conn() as c:
        rows = c.execute("SELECT * FROM condominios ORDER BY nome COLLATE NOCASE, id").fetchall()

    registros = []
    completos = 0
    parciais = 0
    sem_dados = 0
    for row in rows:
        dados = load_data(row)
        banco = clean(dados.get("banco"), 200)
        agencia = clean(dados.get("agencia"), 100)
        conta = clean(dados.get("conta"), 100)
        preenchidos = sum(bool(valor) for valor in (banco, agencia, conta))
        if preenchidos == 3:
            status = "completo"
            completos += 1
        elif preenchidos:
            status = "parcial"
            parciais += 1
        else:
            status = "pendente"
            sem_dados += 1
        registros.append({
            "id": row["id"],
            "nome": clean(dados.get("nome") or row["nome"], 200),
            "banco": banco,
            "agencia": agencia,
            "conta": conta,
            "status": status,
        })

    summary = get_finance_summary(mes)
    with conn() as c:
        condominios = c.execute("SELECT id, nome FROM condominios ORDER BY nome COLLATE NOCASE").fetchall()
        receitas_todas = c.execute(
            "SELECT r.*, c.nome AS condominio FROM financeiro_receitas r LEFT JOIN condominios c ON c.id = r.condominio_id ORDER BY r.mes_referencia DESC, r.created_at DESC, r.id DESC"
        ).fetchall()
        despesas_todas = c.execute(
            "SELECT * FROM financeiro_despesas ORDER BY mes_referencia DESC, vencimento DESC, id DESC"
        ).fetchall()

    categorias = get_finance_categorias()

    editar_receita_id = request.args.get("editar_receita", "").strip()
    editar_despesa_id = request.args.get("editar_despesa", "").strip()
    editar_receita = None
    editar_despesa = None

    with conn() as c:
        if editar_receita_id.isdigit():
            row = c.execute(
                "SELECT r.*, c.nome AS condominio FROM financeiro_receitas r LEFT JOIN condominios c ON c.id = r.condominio_id WHERE r.id = ?",
                (int(editar_receita_id),),
            ).fetchone()
            if row:
                editar_receita = dict(row)

        if editar_despesa_id.isdigit():
            row = c.execute(
                "SELECT * FROM financeiro_despesas WHERE id = ?",
                (int(editar_despesa_id),),
            ).fetchone()
            if row:
                editar_despesa = dict(row)

    return render_template(
        "financeiro.html",
        registros=registros,
        total=len(registros),
        completos=completos,
        parciais=parciais,
        sem_dados=sem_dados,
        summary=summary,
        mes=mes,
        condominios=condominios,
        categorias=categorias,
        receitas_todas=[dict(row) for row in receitas_todas],
        despesas_todas=[dict(row) for row in despesas_todas],
        editar_receita=editar_receita,
        editar_despesa=editar_despesa,
    )


@app.get("/financeiro/categorias")
@login_required
@finance_required
def financeiro_categorias():
    mes = clean(request.args.get("mes", datetime.now().strftime("%Y-%m"))) or datetime.now().strftime("%Y-%m")
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        mes = datetime.now().strftime("%Y-%m")

    dados = get_finance_categorias_page_data(mes)
    return render_template("financeiro_categorias.html", **dados)


@app.post("/financeiro/categorias/salvar")
@login_required
@finance_required
def salvar_categoria():
    nome = clean(request.form.get("nome", ""), 100)
    tipo = clean(request.form.get("tipo", "receita"), 20) or "receita"
    descricao = clean(request.form.get("descricao", ""), 500)

    if not nome:
        flash("Informe o nome da categoria.", "error")
        return redirect(url_for("financeiro_categorias"))

    if tipo not in {"receita", "despesa"}:
        tipo = "receita"

    with conn() as c:
        c.execute(
            "INSERT INTO financeiro_categorias(nome, tipo, descricao, created_at) VALUES(?,?,?,?)",
            (nome, tipo, descricao, datetime.now().isoformat(timespec="seconds")),
        )
        c.commit()

    flash(f"Categoria '{nome}' cadastrada com sucesso.", "ok")
    return redirect(url_for("financeiro_categorias"))


@app.post("/financeiro/categorias/<int:categoria_id>/excluir")
@login_required
@finance_required
def excluir_categoria(categoria_id):
    with conn() as c:
        categoria = c.execute("SELECT nome FROM financeiro_categorias WHERE id = ?", (categoria_id,)).fetchone()
        result = c.execute("DELETE FROM financeiro_categorias WHERE id = ?", (categoria_id,))
        c.commit()

    if result.rowcount:
        flash(f"Categoria '{categoria['nome'] if categoria else categoria_id}' excluída.", "ok")
    else:
        flash("Categoria não encontrada.", "error")
    return redirect(url_for("financeiro", mes=request.args.get("mes") or datetime.now().strftime("%Y-%m")))


@app.get("/financeiro/resumo-categoria")
@login_required
@finance_required
def resumo_categoria():
    mes = clean(request.args.get("mes", datetime.now().strftime("%Y-%m"))) or datetime.now().strftime("%Y-%m")
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        mes = datetime.now().strftime("%Y-%m")

    dados = get_finance_categorias_page_data(mes)
    return render_template("financeiro_resumo_categoria.html", **dados)


@app.post("/financeiro/receitas/salvar")
@login_required
@finance_required
def salvar_receita():
    grupo = clean(request.form.get("grupo", "ALT"), 50) or "ALT"
    condominio_id = request.form.get("condominio_id", "").strip()
    categoria = clean(request.form.get("categoria", ""), 100)
    valor = request.form.get("valor", "")
    data_pagamento = clean(request.form.get("data_pagamento", ""))
    mes_referencia = clean(request.form.get("mes_referencia", datetime.now().strftime("%Y-%m")))
    metodo_pagamento = clean(request.form.get("metodo_pagamento", ""), 50)
    numero_documento = clean(request.form.get("numero_documento", ""), 80)
    status = clean(request.form.get("status", "Recebido"), 50) or "Recebido"
    observacao = clean(request.form.get("observacao", ""), 500)

    try:
        value = parse_monetary(valor)
        datetime.strptime(mes_referencia, "%Y-%m")
        if data_pagamento:
            datetime.strptime(data_pagamento, "%Y-%m-%d")
        if condominio_id:
            condominio_id = int(condominio_id)
            with conn() as c:
                exists = c.execute("SELECT id FROM condominios WHERE id = ?", (condominio_id,)).fetchone()
                if not exists:
                    raise ValueError("Condomínio não encontrado.")
        else:
            condominio_id = None
            grupo = "ALT"
    except (ValueError, TypeError):
        flash("Revise a receita informada: valor, mês e dados do condomínio são obrigatórios.", "error")
        return redirect(url_for("financeiro", mes=mes_referencia))

    with conn() as c:
        c.execute(
            "INSERT INTO financeiro_receitas(condominio_id, grupo, categoria, valor, data_pagamento, mes_referencia, metodo_pagamento, numero_documento, status, observacao, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (condominio_id, grupo, categoria or "Mensalidade", value, data_pagamento or None, mes_referencia, metodo_pagamento or "Transferência", numero_documento or "", status, observacao, datetime.now().isoformat(timespec="seconds")),
        )
        c.commit()

    destino = "ALT" if condominio_id is None else str(condominio_id)
    log_audit("financeiro_receita", f"Receita de R$ {value:,.2f} cadastrada para {destino} por {session.get('username')}", session.get('username'))
    flash("Receita cadastrada com sucesso.", "ok")
    return redirect(url_for("financeiro", mes=mes_referencia))


@app.post("/financeiro/receitas/<int:receita_id>/editar")
@login_required
@finance_required
def editar_receita(receita_id):
    grupo = clean(request.form.get("grupo", "ALT"), 50) or "ALT"
    condominio_id = request.form.get("condominio_id", "").strip()
    categoria = clean(request.form.get("categoria", ""), 100)
    valor = request.form.get("valor", "")
    data_pagamento = clean(request.form.get("data_pagamento", ""))
    mes_referencia = clean(request.form.get("mes_referencia", datetime.now().strftime("%Y-%m")))
    metodo_pagamento = clean(request.form.get("metodo_pagamento", ""), 50)
    numero_documento = clean(request.form.get("numero_documento", ""), 80)
    status = clean(request.form.get("status", "Recebido"), 50) or "Recebido"
    observacao = clean(request.form.get("observacao", ""), 500)

    try:
        value = parse_monetary(valor)
        datetime.strptime(mes_referencia, "%Y-%m")
        if data_pagamento:
            datetime.strptime(data_pagamento, "%Y-%m-%d")
        if condominio_id:
            condominio_id = int(condominio_id)
            with conn() as c:
                exists = c.execute("SELECT id FROM condominios WHERE id = ?", (condominio_id,)).fetchone()
                if not exists:
                    raise ValueError("Condomínio não encontrado.")
        else:
            condominio_id = None
            grupo = "ALT"
    except (ValueError, TypeError):
        flash("Revise a receita informada: valor, mês e dados do condomínio são obrigatórios.", "error")
        return redirect(url_for("financeiro", mes=mes_referencia))

    with conn() as c:
        anterior = c.execute(
            "SELECT categoria, valor, mes_referencia FROM financeiro_receitas WHERE id = ?",
            (receita_id,),
        ).fetchone()
        if anterior is None:
            flash("Receita não encontrada.", "error")
            return redirect(url_for("financeiro", mes=mes_referencia))

        c.execute(
            """UPDATE financeiro_receitas
               SET condominio_id=?, grupo=?, categoria=?, valor=?, data_pagamento=?,
                   mes_referencia=?, metodo_pagamento=?, numero_documento=?, status=?, observacao=?
               WHERE id=?""",
            (condominio_id, grupo, categoria or "Mensalidade", value,
             data_pagamento or None, mes_referencia,
             metodo_pagamento or "Transferência", numero_documento or "",
             status, observacao, receita_id),
        )
        c.commit()

    log_audit(
        "editar_financeiro_receita",
        f"Receita #{receita_id} alterada de R$ {float(anterior['valor']):,.2f} para R$ {value:,.2f} por {session.get('username')}",
        session.get("username"),
    )
    flash("Receita atualizada com sucesso.", "ok")
    return redirect(url_for("financeiro", mes=mes_referencia))


@app.post("/financeiro/receitas/<int:receita_id>/excluir")
@login_required
@finance_required
def excluir_receita(receita_id):
    with conn() as c:
        receita = c.execute("SELECT categoria, valor, mes_referencia FROM financeiro_receitas WHERE id = ?", (receita_id,)).fetchone()
        result = c.execute("DELETE FROM financeiro_receitas WHERE id = ?", (receita_id,))
        c.commit()

    if result.rowcount:
        flash("Receita excluída.", "ok")
    else:
        flash("Receita não encontrada.", "error")
    return redirect(url_for("financeiro", mes=(receita["mes_referencia"] if receita else request.args.get("mes")) or datetime.now().strftime("%Y-%m")))


@app.post("/financeiro/despesas/salvar")
@login_required
@finance_required
def salvar_despesa():
    nome = clean(request.form.get("nome", ""), 200)
    categoria = clean(request.form.get("categoria", ""), 100)
    fornecedor = clean(request.form.get("fornecedor", ""), 200)
    valor = request.form.get("valor", "")
    vencimento = clean(request.form.get("vencimento", ""))
    parcelas = int(request.form.get("parcelas", "1") or 1)
    mes_referencia = clean(request.form.get("mes_referencia", datetime.now().strftime("%Y-%m")))
    metodo_pagamento = clean(request.form.get("metodo_pagamento", ""), 50)
    numero_documento = clean(request.form.get("numero_documento", ""), 80)
    status = clean(request.form.get("status", "Pendente"), 50) or "Pendente"
    observacao = clean(request.form.get("observacao", ""), 500)

    if not nome or not vencimento:
        flash("Informe o nome da despesa e a data de vencimento.", "error")
        return redirect(url_for("financeiro", mes=mes_referencia))

    try:
        value = parse_monetary(valor)
        datetime.strptime(vencimento, "%Y-%m-%d")
        datetime.strptime(mes_referencia, "%Y-%m")
        parcelas = max(1, min(int(parcelas), 24))
    except ValueError:
        flash("Revise os dados da despesa: valor, vencimento e mês obrigatórios.", "error")
        return redirect(url_for("financeiro", mes=mes_referencia))

    items = _create_expense_installments(nome, value, vencimento, parcelas, mes_referencia, observacao)
    with conn() as c:
        c.executemany(
            "INSERT INTO financeiro_despesas(nome, categoria, fornecedor, valor, vencimento, mes_referencia, parcelas, metodo_pagamento, numero_documento, status, observacao, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (item["nome"], categoria or "Geral", fornecedor or "Fornecedor", item["valor"], item["vencimento"], item["mes_referencia"], item["parcelas"], metodo_pagamento or "Transferência", numero_documento or "", status, item["observacao"], datetime.now().isoformat(timespec="seconds"))
                for item in items
            ],
        )
        c.commit()

    log_audit("financeiro_despesa", f"Despesa {nome} cadastrada em {parcelas} parcela(s) por {session.get('username')}", session.get('username'))
    flash(f"Despesa cadastrada com sucesso em {len(items)} parcela(s).", "ok")
    return redirect(url_for("financeiro", mes=mes_referencia))


@app.post("/financeiro/despesas/<int:despesa_id>/editar")
@login_required
@finance_required
def editar_despesa(despesa_id):
    nome = clean(request.form.get("nome", ""), 200)
    categoria = clean(request.form.get("categoria", ""), 100)
    fornecedor = clean(request.form.get("fornecedor", ""), 200)
    valor = request.form.get("valor", "")
    vencimento = clean(request.form.get("vencimento", ""))
    parcelas = request.form.get("parcelas", "1") or "1"
    mes_referencia = clean(request.form.get("mes_referencia", datetime.now().strftime("%Y-%m")))
    metodo_pagamento = clean(request.form.get("metodo_pagamento", ""), 50)
    numero_documento = clean(request.form.get("numero_documento", ""), 80)
    status = clean(request.form.get("status", "Pendente"), 50) or "Pendente"
    observacao = clean(request.form.get("observacao", ""), 500)

    if not nome or not vencimento:
        flash("Informe o nome da despesa e a data de vencimento.", "error")
        return redirect(url_for("financeiro", mes=mes_referencia))

    try:
        value = parse_monetary(valor)
        datetime.strptime(vencimento, "%Y-%m-%d")
        datetime.strptime(mes_referencia, "%Y-%m")
        parcelas = max(1, min(int(parcelas), 24))
    except (ValueError, TypeError):
        flash("Revise os dados da despesa: valor, vencimento e mês obrigatórios.", "error")
        return redirect(url_for("financeiro", mes=mes_referencia))

    with conn() as c:
        anterior = c.execute(
            "SELECT nome, valor, mes_referencia FROM financeiro_despesas WHERE id = ?",
            (despesa_id,),
        ).fetchone()
        if anterior is None:
            flash("Despesa não encontrada.", "error")
            return redirect(url_for("financeiro", mes=mes_referencia))

        c.execute(
            """UPDATE financeiro_despesas
               SET nome=?, categoria=?, fornecedor=?, valor=?, vencimento=?, mes_referencia=?,
                   parcelas=?, metodo_pagamento=?, numero_documento=?, status=?, observacao=?
               WHERE id=?""",
            (nome, categoria or "Geral", fornecedor or "Fornecedor", value,
             vencimento, mes_referencia, parcelas,
             metodo_pagamento or "Transferência", numero_documento or "",
             status, observacao, despesa_id),
        )
        c.commit()

    log_audit(
        "editar_financeiro_despesa",
        f"Despesa #{despesa_id} ({nome}) alterada de R$ {float(anterior['valor']):,.2f} para R$ {value:,.2f} por {session.get('username')}",
        session.get("username"),
    )
    flash("Despesa atualizada com sucesso.", "ok")
    return redirect(url_for("financeiro", mes=mes_referencia))


@app.post("/financeiro/despesas/<int:despesa_id>/excluir")
@login_required
@finance_required
def excluir_despesa(despesa_id):
    with conn() as c:
        despesa = c.execute("SELECT mes_referencia FROM financeiro_despesas WHERE id = ?", (despesa_id,)).fetchone()
        result = c.execute("DELETE FROM financeiro_despesas WHERE id = ?", (despesa_id,))
        c.commit()

    if result.rowcount:
        flash("Despesa excluída.", "ok")
    else:
        flash("Despesa não encontrada.", "error")
    return redirect(url_for("financeiro", mes=(despesa["mes_referencia"] if despesa else request.args.get("mes")) or datetime.now().strftime("%Y-%m")))


@app.get("/financeiro/relatorio")
@login_required
@finance_required
def relatorio_financeiro():
    mes = clean(request.args.get("mes", datetime.now().strftime("%Y-%m"))) or datetime.now().strftime("%Y-%m")
    try:
        datetime.strptime(mes, "%Y-%m")
    except ValueError:
        mes = datetime.now().strftime("%Y-%m")

    summary = get_finance_summary(mes)
    now = datetime.now()
    folder = PDFS / "financeiro" / mes
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"relatorio-financeiro-{mes}-{now:%Y-%m-%d_%H-%M-%S}.pdf"
    path = folder / filename

    story = [
        Paragraph("ALT GESTÃO DE CONDOMÍNIOS", styles["TitleALT"]),
        Paragraph("RELATÓRIO FINANCEIRO DA ALT", styles["SubALT"]),
        Paragraph(f"<b>Mês:</b> {mes}", styles["Value"]),
        Paragraph(f"<b>Receita:</b> R$ {summary['receita']:.2f} &nbsp;&nbsp; <b>Despesa:</b> R$ {summary['despesa']:.2f} &nbsp;&nbsp; <b>Saldo:</b> R$ {summary['saldo']:.2f}", styles["Value"]),
        Spacer(1, 12),
    ]

    receitas_table = [[Paragraph("Condomínio", styles["Label"]), Paragraph("Valor", styles["Label"]), Paragraph("Observação", styles["Label"])] ]
    for item in summary["receitas"]:
        receitas_table.append([
            Paragraph(pdf_value(item.get("condominio") or "Condomínio"), styles["Value"]),
            Paragraph(pdf_value(f"R$ {float(item['valor']):.2f}"), styles["Value"]),
            Paragraph(pdf_value(item.get("observacao") or "-"), styles["Value"]),
        ])
    if len(receitas_table) == 1:
        story.append(Paragraph("Nenhuma receita registrada neste mês.", styles["Value"]))
    else:
        story.append(Paragraph("Receitas", styles["Section"]))
        receitas = Table(receitas_table, colWidths=[180, 120, 220])
        receitas.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F1F6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(receitas)

    story.append(Spacer(1, 12))
    despesas_table = [[Paragraph("Despesa", styles["Label"]), Paragraph("Vencimento", styles["Label"]), Paragraph("Valor", styles["Label"])] ]
    for item in summary["despesas"]:
        despesas_table.append([
            Paragraph(pdf_value(item.get("nome") or "Despesa"), styles["Value"]),
            Paragraph(pdf_value(item.get("vencimento") or "-"), styles["Value"]),
            Paragraph(pdf_value(f"R$ {float(item['valor']):.2f}"), styles["Value"]),
        ])
    if len(despesas_table) == 1:
        story.append(Paragraph("Nenhuma despesa registrada neste mês.", styles["Value"]))
    else:
        story.append(Paragraph("Despesas", styles["Section"]))
        despesas = Table(despesas_table, colWidths=[220, 120, 120])
        despesas.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F1F6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(despesas)

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=38)
    doc.build(story)
    log_audit("financeiro_relatorio", f"Relatório financeiro do mês {mes} gerado por {session.get('username')}", session.get('username'))
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.get("/pdf-carteira")
@login_required
def pdf_wallet():
    tipo = request.args.get("tipo", "Carteira profissional").strip()
    responsavel = request.args.get("responsavel", "").strip()
    if not responsavel:
        abort(400, description="Responsável da carteira não informado.")

    with conn() as c:
        rows = c.execute("SELECT * FROM condominios ORDER BY nome COLLATE NOCASE").fetchall()

    matches = []
    for row in rows:
        d = load_data(row)
        wallet_tipo = "Carteira profissional" if d.get("sindicoTipo") == "Profissional" else "Carteira morador" if d.get("sindicoTipo") == "Morador" else "Sem tipo"
        if tipo not in ("todos", wallet_tipo):
            continue
        responsavel_atual = clean(d.get("responsavelSindico"), 200) or clean(d.get("empresaSindico"), 200) or clean(d.get("sindico"), 200) or ""
        if responsavel_atual.lower() == responsavel.lower():
            matches.append((row, d))

    if not matches:
        return "Carteira não encontrada", 404

    now = datetime.now()
    nome_carteira = responsavel
    folder = PDFS / "carteiras" / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    arquivo = f"carteira-{safe_name(nome_carteira)}-{now:%Y-%m-%d_%H-%M-%S}.pdf"
    path = folder / arquivo

    story = [
        Paragraph("ALT GESTÃO DE CONDOMÍNIOS", styles["TitleALT"]),
        Paragraph("RELATÓRIO COMPLETO DA CARTEIRA", styles["SubALT"]),
        Paragraph(f"<b>Responsável:</b> {html.escape(nome_carteira)}", styles["Value"]),
        Paragraph(f"<b>Tipo:</b> {html.escape(tipo)}", styles["Value"]),
        Paragraph(f"<b>Condomínios:</b> {len(matches)}", styles["Value"]),
        Spacer(1, 12),
    ]

    for row, d in matches:
        nome_condominio = clean(d.get("nome") or row["nome"], 200)
        story.append(Paragraph(f"<b>{html.escape(nome_condominio)}</b>", styles["Section"]))
        lead_rows = [
            ("CNPJ", d.get("cnpj") or "—"),
            ("Unidades", d.get("unidades") or "—"),
            ("Endereço", address_text(d.get("endereco")) or "—"),
            ("Tipo de síndico", d.get("sindicoTipo") or "—"),
        ]
        if d.get("sindicoTipo") == "Profissional":
            lead_rows.extend([
                ("Empresa", d.get("empresaSindico") or "—"),
                ("CNPJ da empresa", d.get("cnpjEmpresaSindico") or "—"),
                ("Síndico responsável", d.get("responsavelSindico") or "—"),
                ("Telefone do responsável", d.get("telResponsavelSindico") or "—"),
            ])
        else:
            lead_rows.extend([
                ("Nome do síndico", d.get("sindico") or "—"),
                ("CPF", d.get("cpfSindico") or "—"),
                ("Unidade", d.get("unSindico") or "—"),
                ("Telefone", d.get("telSindico") or "—"),
                ("E-mail", d.get("emailSindico") or "—"),
            ])
        lead_rows.extend([
            ("Ata de eleição", format_date(d.get("ataEleicao")) or "—"),
            ("Última AGO", format_date(d.get("ultAGO")) or "—"),
            ("Início do mandato", format_date(d.get("inicioMandato")) or "—"),
            ("Fim do mandato", format_date(d.get("fimMandato")) or "—"),
            ("PPCI", yn(d.get("ppci"))),
            ("Validade do PPCI", format_date(d.get("validPpci")) or "—"),
            ("Extintores", yn(d.get("ext"))),
            ("Última recarga", format_date(d.get("recarga")) or "—"),
            ("Brigadistas", yn(d.get("brig"))),
            ("Quantidade de brigadistas", d.get("qtdBrig") or "—"),
            ("Conselho fiscal", yn(d.get("conselho"))),
            ("Quantidade de conselheiros", d.get("qtdConselheiros") or "—"),
        ])
        add_section(story, "Dados gerais", lead_rows)
        add_section(story, "Documentação", [
            ("Convenção", yn(d.get("conv"))),
            ("Convenção impressa", yn(d.get("convFis"))),
            ("Regimento interno", yn(d.get("reg"))),
            ("Regimento impresso", yn(d.get("regFis"))),
            ("Administracão impressa", yn(d.get("admFis"))),
            ("PPCI impresso", yn(d.get("ppciFis"))),
            ("Extintores impressos", yn(d.get("extFis"))),
            ("Caixa d'água", format_date(d.get("cxData")) or "—"),
            ("Comprovante da caixa d'água", yn(d.get("cxFis"))),
            ("Dedetização", format_date(d.get("dedData")) or "—"),
            ("Comprovante da dedetização", yn(d.get("dedFis"))),
            ("Segurança", yn(d.get("seguranca"))),
            ("Empresa de segurança", d.get("empresaSeg") or "—"),
            ("Gás", yn(d.get("gas"))),
            ("Tipo de gás", d.get("gasTipo") or "—"),
            ("Código do gás", d.get("codCad") or "—"),
        ])
        if d.get("conselheiros"):
            rows_conselho = []
            for i, item in enumerate(d.get("conselheiros", []), 1):
                rows_conselho.extend([
                    (f"Conselheiro {i} - nome", item.get("nome") or "—"),
                    (f"Conselheiro {i} - unidade", item.get("unidade") or "—"),
                ])
            add_section(story, "Conselho fiscal", rows_conselho)
        if d.get("brigadistas"):
            rows_brig = []
            for i, item in enumerate(d.get("brigadistas", []), 1):
                rows_brig.extend([
                    (f"Brigadista {i} - nome", item.get("nome") or "—"),
                    (f"Brigadista {i} - unidade", item.get("unidade") or "—"),
                ])
            add_section(story, "Brigadistas", rows_brig)
        story.append(Spacer(1, 10))

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=38)
    doc.build(story)
    return send_file(path, as_attachment=True, download_name=arquivo, mimetype="application/pdf")

@app.route("/editar/<int:cid>")
@login_required
def editar(cid):
    with conn() as c: row = c.execute("SELECT * FROM condominios WHERE id=?", (cid,)).fetchone()
    if not row: return "Condomínio não encontrado", 404
    d = load_data(row)
    d["alert_status"] = get_condominio_alert_status(d)
    return render_template("form.html", d=d, cid=cid, today=datetime.now().strftime("%Y-%m-%d"))


@app.post("/salvar")
@login_required
def salvar():
    try: d = collect_form(request.form)
    except ValueError as exc:
        flash(f"Revise os dados: {exc}.", "error"); return redirect(request.referrer or url_for("index"))
    if not d["nome"]:
        flash("Informe o nome do condomínio.", "error"); return redirect(request.referrer or url_for("index"))
    cid_raw = request.form.get("id", "").strip(); cid = int(cid_raw) if cid_raw.isdigit() else None
    saved = save_condominio(d, cid)
    if saved is None:
        flash("O cadastro não foi encontrado para atualização.", "error"); return redirect(url_for("index"))
    auto_backup()
    log_audit("salvar", f"Cadastro {d['nome']} salvo/alterado por {session.get('username')}", session.get('username'))
    return redirect(url_for("salvo", cid=saved))


@app.get("/salvo/<int:cid>")
@login_required
def salvo(cid):
    with conn() as c:
        row = c.execute("SELECT id,nome,atualizado_em FROM condominios WHERE id=?", (cid,)).fetchone()
    if not row:
        return redirect(url_for("index"))
    try:
        data = datetime.fromisoformat(row["atualizado_em"]).strftime("%d/%m/%Y às %H:%M")
    except ValueError:
        data = row["atualizado_em"]
    return render_template("salvo.html", cid=cid, nome=row["nome"], atualizado=data)


@app.post("/excluir/<int:cid>")
@login_required
def excluir(cid):
    with conn() as c:
        row = c.execute("SELECT nome FROM condominios WHERE id=?", (cid,)).fetchone()
        cur = c.execute("DELETE FROM condominios WHERE id=?", (cid,))
        c.commit()
    flash("Cadastro excluído." if cur.rowcount else "Cadastro não encontrado.", "ok" if cur.rowcount else "error")
    if cur.rowcount:
        auto_backup()
        log_audit("excluir", f"Cadastro {row['nome'] if row else cid} excluído por {session.get('username')}", session.get('username'))
    return redirect(url_for("index"))


@app.get("/exportar-json")
@login_required
def exportar_json():
    with conn() as c: rows = c.execute("SELECT id,nome,atualizado_em,dados_json FROM condominios ORDER BY id").fetchall()
    payload = {"versao": 3, "exportado_em": datetime.now().isoformat(timespec="seconds"), "condominios": [{"id":r["id"],"nome":r["nome"],"atualizado_em":r["atualizado_em"],"dados":load_data(r)} for r in rows]}
    b = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    log_audit("exportar_json", f"Exportação JSON solicitada por {session.get('username')}", session.get('username'))
    return send_file(b, as_attachment=True, download_name=f"ALT-backup-{datetime.now():%Y-%m-%d_%H-%M-%S}.json", mimetype="application/json")


@app.post("/importar-json")
@login_required
def importar_json():
    f = request.files.get("arquivo")
    if not f or not f.filename.lower().endswith(".json"):
        flash("Selecione um arquivo JSON de backup.", "error"); return redirect(url_for("index"))
    try:
        payload = json.load(f.stream)
        items = payload.get("condominios") if isinstance(payload, dict) else None
        if not isinstance(items, list) or len(items) > 5000:
            raise ValueError("estrutura inválida")
        prepared = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("dados"), dict):
                continue
            raw=item["dados"]
            d={f:clean(raw.get(f,"")) for f in FIELDS}
            d["nome"]=clean(raw.get("nome"),200)
            if not d["nome"]:
                continue
            d["endereco"]=normalize_address(raw); d["conselheiros"]=normalize_conselheiros(raw); d["brigadistas"]=normalize_brigadistas(raw)
            prepared.append(d)
        if not prepared:
            raise ValueError("nenhum cadastro válido encontrado")
        auto_backup()
        with conn() as c:
            c.executemany("INSERT INTO condominios(nome,atualizado_em,dados_json) VALUES(?,?,?)", [(d["nome"],datetime.now().isoformat(timespec="seconds"),json.dumps(d,ensure_ascii=False)) for d in prepared])
            c.commit()
        flash(f"{len(prepared)} registro(s) importado(s). Registros existentes não foram sobrescritos.", "ok")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        logging.warning("Falha na validação da importação: %s", exc)
        flash("Arquivo inválido ou sem cadastros válidos. Nenhum dado foi importado.", "error")
    except sqlite3.Error:
        logging.exception("Falha no banco durante a importação")
        flash("Não foi possível importar o arquivo. Nenhum dado foi importado.", "error")
    return redirect(url_for("index"))


def safe_name(name):
    name=secure_filename(clean(name,200)) or "condominio"
    return re.sub(r"[^A-Za-z0-9._-]+","_",name)[:100]


def yn(v): return "Sim" if v=="Sim" else "Não" if v=="Não" else "—"

def pdf_value(value): return html.escape(str(value)).replace("\n","<br/>")


def resolve_report_status(status_name):
    status_map = {
        "vencidos": "red",
        "vai-vencer": "yellow",
        "vai_vencer": "yellow",
        "proximos": "yellow",
        "próximos": "yellow",
        "em-dia": "green",
        "em_dia": "green",
        "all": None,
        "todos": None,
    }
    return status_map.get((status_name or "").strip().lower())


def build_report_rows(status_name):
    target = resolve_report_status(status_name)
    rows = []
    with conn() as c:
        registros = c.execute("SELECT * FROM condominios ORDER BY nome COLLATE NOCASE").fetchall()
    for row in registros:
        d = load_data(row)
        nome = clean(d.get("nome") or row["nome"], 200)
        for issue in get_condominio_alert_status(d).get("issues", []):
            if target is not None and issue.get("status") != target:
                continue
            rows.append({
                "nome": nome,
                "item": issue.get("label", "Item"),
                "data": issue.get("date_label") or issue.get("date") or "",
                "status": issue.get("status", "green"),
            })
    return rows


def format_date(value):
    try: return datetime.strptime(value,"%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError,TypeError): return value or ""

def address_text(addr):
    if not isinstance(addr,dict): return clean(addr)
    parts=[]
    if addr.get("rua"): parts.append(addr["rua"] + (f", {addr['numero']}" if addr.get("numero") else ""))
    if addr.get("complemento"): parts.append(addr["complemento"])
    if addr.get("bairro"): parts.append(addr["bairro"])
    city=" - ".join(x for x in (addr.get("cidade"),addr.get("estado")) if x)
    if city: parts.append(city)
    if addr.get("cep"): parts.append("CEP " + addr["cep"])
    return ", ".join(parts)


def add_section(story,title,rows):
    story.append(Paragraph(title,styles["Section"]))
    data=[]
    for label,value in rows:
        if value not in ("",None,[],{}): data.append([Paragraph(pdf_value(label),styles["Label"]),Paragraph(pdf_value(value),styles["Value"])])
    if data:
        t=Table(data,colWidths=[175,350]); t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#D9D9D9")),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#F4F1F6")),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)])); story.append(t); story.append(Spacer(1,8))


styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleALT",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=17,textColor=colors.HexColor("#4F2C68"),alignment=TA_CENTER,spaceAfter=4))
styles.add(ParagraphStyle(name="SubALT",parent=styles["Normal"],fontSize=9,textColor=colors.HexColor("#737373"),alignment=TA_CENTER,spaceAfter=15))
styles.add(ParagraphStyle(name="Section",parent=styles["Heading2"],fontSize=11,textColor=colors.HexColor("#4F2C68"),spaceBefore=10,spaceAfter=6))
styles.add(ParagraphStyle(name="Label",parent=styles["Normal"],fontSize=8,textColor=colors.HexColor("#737373")))
styles.add(ParagraphStyle(name="Value",parent=styles["Normal"],fontSize=8.5,textColor=colors.black))


@app.get("/relatorio")
@login_required
def relatorio():
    tipo = (request.args.get("tipo") or "vencidos").strip().lower()
    status_labels = {
        "todos": "Todos os relatórios",
        "all": "Todos os relatórios",
        "vencidos": "Vencidos",
        "vai-vencer": "Vai vencer",
        "vai_vencer": "Vai vencer",
        "em-dia": "Em dia",
        "em_dia": "Em dia",
        "proximos": "Vai vencer",
        "próximos": "Vai vencer",
    }
    target = resolve_report_status(tipo)
    title = status_labels.get(tipo, "Vencidos")
    groups = [
        ("Vencidos", build_report_rows("vencidos")),
        ("Vai vencer", build_report_rows("vai-vencer")),
        ("Em dia", build_report_rows("em-dia")),
    ] if target is None else [(title, build_report_rows(tipo))]

    now = datetime.now()
    folder = PDFS / "relatorios" / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"relatorio-{tipo or 'vencidos'}-{now:%Y-%m-%d_%H-%M-%S}.pdf"
    path = folder / filename

    story = [
        Paragraph("ALT GESTÃO DE CONDOMÍNIOS", styles["TitleALT"]),
        Paragraph("RELATÓRIO DE VENCIMENTOS", styles["SubALT"]),
        Paragraph(f"<b>Filtro:</b> {html.escape(title)}", styles["Value"]),
        Spacer(1, 12),
    ]

    for label, rows in groups:
        table_data = [[Paragraph("Condomínio", styles["Label"]), Paragraph("Item", styles["Label"]), Paragraph("Data", styles["Label"])]]
        for item in rows:
            table_data.append([
                Paragraph(pdf_value(item["nome"]), styles["Value"]),
                Paragraph(pdf_value(item["item"]), styles["Value"]),
                Paragraph(pdf_value(item["data"]), styles["Value"]),
            ])
        if len(table_data) == 1:
            story.append(Paragraph(f"{label}: nenhum item encontrado.", styles["Value"]))
            story.append(Spacer(1, 6))
            continue
        story.append(Paragraph(label, styles["Section"]))
        table = Table(table_data, colWidths=[220, 200, 100])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F1F6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=38)
    doc.build(story)
    log_audit("relatorio", f"Relatório {title} gerado por {session.get('username')}", session.get('username'))
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.get("/relatorio-projeto")
@login_required
def relatorio_projeto():
    with conn() as c:
        condominios = c.execute("SELECT * FROM condominios ORDER BY nome COLLATE NOCASE, id").fetchall()
        usuarios = c.execute("SELECT username, role FROM usuarios ORDER BY username COLLATE NOCASE").fetchall()

    total_unidades = 0
    profissionais = 0
    moradores = 0
    sem_tipo = 0
    alertas = {"red": 0, "yellow": 0, "green": 0}
    status_labels_for_pdf = {"red": "Vencido", "yellow": "Próximo do vencimento", "green": "Em dia"}
    resumo_condominios = []
    for row in condominios:
        dados = load_data(row)
        tipo = dados.get("sindicoTipo")
        if tipo == "Profissional":
            profissionais += 1
        elif tipo == "Morador":
            moradores += 1
        else:
            sem_tipo += 1
        try:
            total_unidades += int(dados.get("unidades") or 0)
        except (TypeError, ValueError):
            pass
        status = get_condominio_alert_status(dados).get("level", "green")
        alertas[status] = alertas.get(status, 0) + 1
        resumo_condominios.append((
            clean(dados.get("nome") or row["nome"], 200),
            tipo or "Não informado",
            status_labels_for_pdf.get(status, "Em dia"),
            row["atualizado_em"],
        ))

    role_counts = {}
    for usuario in usuarios:
        role_counts[usuario["role"]] = role_counts.get(usuario["role"], 0) + 1

    now = datetime.now()
    folder = PDFS / "relatorios" / "projeto"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"relatorio-resumo-projeto-{now:%Y-%m-%d_%H-%M-%S}.pdf"
    path = folder / filename
    story = [
        Paragraph("ALT GESTÃO DE CONDOMÍNIOS", styles["TitleALT"]),
        Paragraph("RESUMO DO PROJETO", styles["SubALT"]),
        Paragraph(f"<b>Gerado em:</b> {now:%d/%m/%Y %H:%M}", styles["Value"]),
        Spacer(1, 12),
    ]
    add_section(story, "1. ESTADO ATUAL", [
        ("Aplicação", "Flask com banco SQLite"),
        ("Autenticação", "Login com senha protegida e sessão segura"),
        ("Exportações", "PDFs de cadastros, carteiras, vencimentos, auditoria e este resumo"),
        ("Testes automatizados", "Suíte de testes com 21 casos aprovados"),
    ])
    add_section(story, "2. CADASTROS", [
        ("Condomínios cadastrados", len(condominios)),
        ("Total de unidades informadas", total_unidades),
        ("Síndicos profissionais", profissionais),
        ("Síndicos moradores", moradores),
        ("Sem tipo de síndico informado", sem_tipo),
    ])
    add_section(story, "3. USUÁRIOS E PERMISSÕES", [
        ("Usuários cadastrados", len(usuarios)),
        ("Administradores", role_counts.get("admin", 0)),
        ("Usuários financeiros", role_counts.get("financeiro", 0)),
        ("Usuários normais", role_counts.get("normal", 0)),
        ("Área financeira", "Disponível para admin e financeiro"),
        ("Administração e auditoria", "Restritas ao perfil admin"),
    ])
    add_section(story, "4. MONITORAMENTO", [
        ("Condomínios com pendências vencidas", alertas.get("red", 0)),
        ("Condomínios próximos do vencimento", alertas.get("yellow", 0)),
        ("Condomínios em dia", alertas.get("green", 0)),
        ("Auditoria", "Registro de login, alterações e exportações"),
    ])
    story.append(Paragraph("5. RESUMO DOS CONDOMÍNIOS", styles["Section"]))
    table_data = [[
        Paragraph("Condomínio", styles["Label"]),
        Paragraph("Síndico", styles["Label"]),
        Paragraph("Situação", styles["Label"]),
        Paragraph("Atualizado em", styles["Label"]),
    ]]
    for nome, tipo, status, atualizado in resumo_condominios:
        table_data.append([
            Paragraph(pdf_value(nome), styles["Value"]),
            Paragraph(pdf_value(tipo), styles["Value"]),
            Paragraph(pdf_value(status), styles["Value"]),
            Paragraph(pdf_value(atualizado), styles["Value"]),
        ])
    if len(table_data) == 1:
        story.append(Paragraph("Nenhum condomínio cadastrado.", styles["Value"]))
    else:
        table = Table(table_data, colWidths=[190, 110, 100, 120])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F1F6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=38)
    doc.build(story)
    log_audit("relatorio_projeto", f"Resumo do projeto gerado por {session.get('username')}", session.get("username"))
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.get("/pdf/<int:cid>")
@login_required
def pdf(cid):
    with conn() as c: row=c.execute("SELECT * FROM condominios WHERE id=?",(cid,)).fetchone()
    if not row: return "Condomínio não encontrado",404
    d=load_data(row); name=clean(d.get("nome"),200) or "Condomínio"; now=datetime.now()
    folder=PDFS/safe_name(name)/now.strftime("%Y-%m-%d"); folder.mkdir(parents=True,exist_ok=True)
    filename=f"{safe_name(name)}-Atualizacao-{now:%Y-%m-%d_%H-%M-%S}.pdf"; path=folder/filename
    doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=36,leftMargin=36,topMargin=38,bottomMargin=38,title=f"ALT - {name}",author="ALT Gestão de Condomínios")
    try: date_text=datetime.fromisoformat(row["atualizado_em"]).strftime("%d/%m/%Y")
    except ValueError: date_text=now.strftime("%d/%m/%Y")
    story=[Paragraph("ALT GESTÃO DE CONDOMÍNIO",styles["TitleALT"]),Paragraph("FICHA DE CADASTRAMENTO E ATUALIZAÇÃO",styles["SubALT"]),Paragraph(f"<b>Condomínio:</b> {pdf_value(name)} &nbsp;&nbsp; <b>Data:</b> {date_text}",styles["Value"]),Spacer(1,10)]
    add_section(story,"1. DADOS DO CONDOMÍNIO",[("Nome completo",d.get("nome")),("CNPJ",d.get("cnpj")),("Endereço",address_text(d.get("endereco"))), ("Quantidade de unidades",d.get("unidades"))])
    sindico_rows=[("Tipo de síndico",d.get("sindicoTipo"))]
    if d.get("sindicoTipo")=="Profissional":
        sindico_rows += [("Empresa",d.get("empresaSindico")),("CNPJ da empresa",d.get("cnpjEmpresaSindico")),("Síndico responsável",d.get("responsavelSindico")),("Telefone do responsável",d.get("telResponsavelSindico"))]
    else:
        sindico_rows += [("Nome completo",d.get("sindico")),("CPF",d.get("cpfSindico")),("Unidade/Apartamento",d.get("unSindico")),("Telefone",d.get("telSindico")),("E-mail",d.get("emailSindico"))]
    sindico_rows += [("Data da ata de eleição",format_date(d.get("ataEleicao"))), ("Última AGO",format_date(d.get("ultAGO"))), ("Início do mandato",format_date(d.get("inicioMandato"))), ("Vencimento do mandato",format_date(d.get("fimMandato")))]
    add_section(story,"2. SÍNDICO",sindico_rows)
    council=[("Possui Conselho Fiscal",yn(d.get("conselho"))),("Quantidade de conselheiros",d.get("qtdConselheiros"))]
    for i,x in enumerate(d.get("conselheiros",[]),1): council += [(f"Conselheiro {i} - nome",x.get("nome")),(f"Conselheiro {i} - unidade",x.get("unidade"))]
    add_section(story,"3. CONSELHO FISCAL",council)
    add_section(story,"4. DADOS BANCÁRIOS",[("Banco",d.get("banco")),("Agência",d.get("agencia")),("Conta",d.get("conta"))])
    add_section(story,"5. DOCUMENTAÇÃO",[("Convenção",yn(d.get("conv"))), ("Convenção impressa",yn(d.get("convFis"))), ("Regimento Interno",yn(d.get("reg"))), ("Regimento impresso",yn(d.get("regFis"))), ("Contrato da administração impresso",yn(d.get("admFis")))])
    add_section(story,"6. PPCI E SEGURANÇA CONTRA INCÊNDIO",[("Possui PPCI",yn(d.get("ppci"))), ("Validade do PPCI",format_date(d.get("validPpci"))), ("PPCI impresso",yn(d.get("ppciFis"))), ("Extintores regulares",yn(d.get("ext"))), ("Última recarga",format_date(d.get("recarga"))), ("Documento dos extintores impresso",yn(d.get("extFis"))), ("Possui brigadistas",yn(d.get("brig"))), ("Quantidade de brigadistas",d.get("qtdBrig"))])
    for i,b in enumerate(d.get("brigadistas",[]),1): add_section(story,f"BRIGADISTA {i}",[("Nome",b.get("nome")),("Unidade",b.get("unidade"))])
    add_section(story,"7. LIMPEZA DA CAIXA D'ÁGUA E DEDETIZAÇÃO",[("Última limpeza da caixa d'água",format_date(d.get("cxData"))), ("Comprovante impresso",yn(d.get("cxFis"))), ("Última dedetização",format_date(d.get("dedData"))), ("Comprovante da dedetização impresso",yn(d.get("dedFis")))])
    add_section(story,"8. SEGURO PREDIAL",[("Possui seguro",yn(d.get("seg"))), ("Empresa/Seguradora",d.get("segEmpresa")), ("Última contratação/renovação",format_date(d.get("segData"))), ("Apólice impressa",yn(d.get("segFis")))])
    add_section(story,"9. CONTAS DE CONSUMO",[("Código da conta de luz",d.get("luz")),("Código da conta de água",d.get("agua")),("Possui gás",yn(d.get("gas"))), ("Gás - responsável",d.get("gasTipo")), ("Código de cadastramento",d.get("codCad")), ("Empresa de gás",d.get("empresaGas")), ("Código para cadastro",d.get("codigoGasOutra"))])
    add_section(story,"10. LIMPEZA",[("Quem realiza",d.get("quemLimpeza")),("Empresa",d.get("empresaLimpeza")),("Frequência",d.get("freqLimpeza")),("Carga horária",d.get("cargaLimpeza")),("Contrato impresso",yn(d.get("limpFis")))])
    add_section(story,"11. SEGURANÇA",[("Possui segurança",yn(d.get("seguranca"))), ("Empresa",d.get("empresaSeg")), ("Contrato impresso",yn(d.get("segFis2")))])
    add_section(story,"12. JURÍDICO / COBRANÇA",[("Possui advogado/escritório",yn(d.get("juridico"))), ("Nome",d.get("nomeJuridico")),("Percentual de cobrança",d.get("percCobranca")),("Contrato jurídico impresso",yn(d.get("jurFis")))])
    add_section(story,"13. MERCADINHO",[("Possui mercadinho",yn(d.get("mercadinho"))), ("Nome",d.get("nomeMerc")),("Responsável",d.get("respMerc")),("Contato",d.get("contatoMerc")),("Repasse",d.get("repasseMerc")),("Periodicidade",d.get("periodoMerc")),("Data/período",d.get("dataMerc")),("Contrato impresso",yn(d.get("mercFis")))])
    add_section(story,"14. OBSERVAÇÕES",[("Observações",d.get("obs"))])
    doc.build(story)
    log_audit("pdf", f"PDF gerado para {name} por {session.get('username')}", session.get('username'))
    return send_file(path,as_attachment=(request.args.get("visualizar") != "1"),download_name=filename,mimetype="application/pdf")


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error): flash("O arquivo enviado excede o limite de 10 MB.","error"); return redirect(url_for("index"))
@app.errorhandler(400)
def bad_request(error): return f"Solicitação inválida: {html.escape(str(error.description))}",400
@app.errorhandler(404)
def not_found(_error): return "Página ou cadastro não encontrado.",404

if __name__ == "__main__":
    init_db(); serve(app,host="127.0.0.1",port=PORT,threads=4,ident="ALT-Condominios")
