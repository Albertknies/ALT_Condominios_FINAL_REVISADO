"""
Migração robusta do SQLite local da ALT para PostgreSQL/Neon.
- Preserva os dados do SQLite.
- Inclui usuario_condominios.
- Cria/adiciona colunas que existirem no SQLite e faltarem no Neon.
- Funciona também com tabelas sem coluna id.
- NÃO mostra a DATABASE_URL.
"""
import os
import sqlite3
import sys
from pathlib import Path
import psycopg

BASE = Path(__file__).resolve().parent
SQLITE_DB = Path(os.environ.get("ALT_SQLITE_DB", BASE / "data" / "alt.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if not DATABASE_URL:
    print("ERRO: defina DATABASE_URL.")
    sys.exit(1)
if not SQLITE_DB.exists():
    print(f"ERRO: banco SQLite não encontrado: {SQLITE_DB}")
    sys.exit(1)

TABLES = [
    "condominios",
    "usuarios",
    "usuario_condominios",
    "auditoria",
    "financeiro_receitas",
    "financeiro_despesas",
    "financeiro_categorias",
]

DDL = {
    "condominios": """
        CREATE TABLE IF NOT EXISTS condominios (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            atualizado_em TEXT NOT NULL,
            dados_json TEXT NOT NULL
        )""",
    "usuarios": """
        CREATE TABLE IF NOT EXISTS usuarios (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )""",
    "usuario_condominios": """
        CREATE TABLE IF NOT EXISTS usuario_condominios (
            usuario_id BIGINT NOT NULL,
            condominio_id BIGINT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
            PRIMARY KEY (usuario_id, condominio_id),
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY(condominio_id) REFERENCES condominios(id) ON DELETE CASCADE
        )""",
    "auditoria": """
        CREATE TABLE IF NOT EXISTS auditoria (
            id BIGSERIAL PRIMARY KEY,
            username TEXT,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )""",
    "financeiro_receitas": """
        CREATE TABLE IF NOT EXISTS financeiro_receitas (
            id BIGSERIAL PRIMARY KEY,
            condominio_id BIGINT,
            grupo TEXT NOT NULL DEFAULT 'ALT',
            categoria TEXT,
            valor DOUBLE PRECISION NOT NULL,
            data_pagamento TEXT,
            mes_referencia TEXT NOT NULL,
            metodo_pagamento TEXT,
            numero_documento TEXT,
            status TEXT DEFAULT 'Recebido',
            observacao TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
            FOREIGN KEY(condominio_id) REFERENCES condominios(id) ON DELETE CASCADE
        )""",
    "financeiro_despesas": """
        CREATE TABLE IF NOT EXISTS financeiro_despesas (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria TEXT,
            fornecedor TEXT,
            valor DOUBLE PRECISION NOT NULL,
            vencimento TEXT NOT NULL,
            mes_referencia TEXT NOT NULL,
            parcelas INTEGER NOT NULL DEFAULT 1,
            metodo_pagamento TEXT,
            numero_documento TEXT,
            status TEXT DEFAULT 'Pendente',
            observacao TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )""",
    "financeiro_categorias": """
        CREATE TABLE IF NOT EXISTS financeiro_categorias (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'receita',
            descricao TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )""",
}

def sqlite_info(conn, table):
    return conn.execute(f"PRAGMA table_info({table})").fetchall()

def pg_columns(cur, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (table,))
    return {r[0] for r in cur.fetchall()}

def pg_type(sqlite_type):
    t = (sqlite_type or "").upper()
    if "INT" in t:
        return "BIGINT"
    if any(x in t for x in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if "BLOB" in t:
        return "BYTEA"
    return "TEXT"

def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'

def order_sql(cols):
    names = [r[1] for r in cols]
    return " ORDER BY id" if "id" in names else ""

def main():
    print(f"SQLite: {SQLITE_DB}")
    print("Neon: conexão configurada.")
    print()
    print("ATENÇÃO: os dados existentes nas tabelas da ALT no Neon serão substituídos pelos dados do SQLite.")
    answer = input("Digite MIGRAR para continuar: ").strip()
    if answer != "MIGRAR":
        print("Migração cancelada.")
        return

    sc = sqlite3.connect(SQLITE_DB)
    sc.row_factory = sqlite3.Row
    try:
        with psycopg.connect(DATABASE_URL) as pg:
            with pg.cursor() as cur:
                # Garante as tabelas base.
                for table in TABLES:
                    cur.execute(DDL[table])

                # Garante colunas presentes no SQLite e ausentes no Neon.
                for table in TABLES:
                    infos = sqlite_info(sc, table)
                    existing = pg_columns(cur, table)
                    for row in infos:
                        col = row[1]
                        if col not in existing:
                            typ = pg_type(row[2])
                            cur.execute(f"ALTER TABLE {quote_ident(table)} ADD COLUMN {quote_ident(col)} {typ}")
                            print(f"  + coluna adicionada: {table}.{col} ({typ})")

                # Limpa respeitando vínculos.
                for table in ["usuario_condominios", "financeiro_receitas", "financeiro_despesas", "financeiro_categorias", "auditoria", "usuarios", "condominios"]:
                    cur.execute(f"DELETE FROM {quote_ident(table)}")

                # Copia na ordem necessária para FKs.
                copy_order = ["condominios", "usuarios", "financeiro_receitas", "financeiro_despesas", "financeiro_categorias", "auditoria", "usuario_condominios"]
                for table in copy_order:
                    infos = sqlite_info(sc, table)
                    if not infos:
                        print(f"{table}: 0 registros")
                        continue
                    src_cols = [r[1] for r in infos]
                    target_cols = pg_columns(cur, table)
                    cols = [c for c in src_cols if c in target_cols]
                    rows = sc.execute(f"SELECT {', '.join(quote_ident(c) for c in src_cols)} FROM {quote_ident(table)}{order_sql(infos)}").fetchall()
                    if not rows:
                        print(f"{table}: 0 registros")
                        continue
                    placeholders = ", ".join(["%s"] * len(cols))
                    sql = f"INSERT INTO {quote_ident(table)} ({', '.join(quote_ident(c) for c in cols)}) VALUES ({placeholders})"
                    for row in rows:
                        cur.execute(sql, tuple(row[c] for c in cols))
                    print(f"{table}: {len(rows)} registros")

                # Ajusta sequências somente onde há id.
                for table in TABLES:
                    infos = sqlite_info(sc, table)
                    if not any(r[1] == "id" for r in infos):
                        continue
                    cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                    seq = cur.fetchone()[0]
                    if seq:
                        cur.execute(f"SELECT MAX(id) FROM {quote_ident(table)}")
                        max_id = cur.fetchone()[0]
                        if max_id is not None:
                            cur.execute("SELECT setval(%s, %s, true)", (seq, max_id))
            pg.commit()
        print()
        print("MIGRAÇÃO CONCLUÍDA COM SUCESSO.")
    except Exception as e:
        print()
        print("ERRO NA MIGRAÇÃO:")
        print(type(e).__name__ + ":", e)
        print("Nenhuma alteração desta execução foi confirmada no Neon.")
        sys.exit(1)
    finally:
        sc.close()

if __name__ == "__main__":
    main()
