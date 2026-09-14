"""
Migração do SQLite local da ALT para o PostgreSQL/Neon.

USO:
1. Faça uma cópia do data/alt.db antes.
2. Configure DATABASE_URL com a conexão do Neon.
3. Execute:
   python migrar_sqlite_neon.py

ATENÇÃO:
- Este script limpa os dados das tabelas da ALT no Neon antes de copiar o SQLite.
- Use somente no banco Neon destinado à ALT.
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
    print("ERRO: defina a variável DATABASE_URL com a conexão do Neon.")
    sys.exit(1)

if not SQLITE_DB.exists():
    print(f"ERRO: banco SQLite não encontrado: {SQLITE_DB}")
    sys.exit(1)

TABLES = [
    "condominios",
    "usuarios",
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
        )
    """,
    "usuarios": """
        CREATE TABLE IF NOT EXISTS usuarios (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
    """,
    "auditoria": """
        CREATE TABLE IF NOT EXISTS auditoria (
            id BIGSERIAL PRIMARY KEY,
            username TEXT,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
    """,
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
        )
    """,
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
        )
    """,
    "financeiro_categorias": """
        CREATE TABLE IF NOT EXISTS financeiro_categorias (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'receita',
            descricao TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
    """,
}

def sqlite_columns(cur, table):
    return [row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]

def main():
    print(f"SQLite: {SQLITE_DB}")
    print("Neon: conexão configurada.")
    print()
    print("ATENÇÃO: os dados existentes nas tabelas da ALT no Neon serão substituídos pelos dados do SQLite.")
    answer = input("Digite MIGRAR para continuar: ").strip()
    if answer != "MIGRAR":
        print("Migração cancelada.")
        return

    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row

    try:
        with psycopg.connect(DATABASE_URL) as pg:
            with pg.cursor() as cur:
                for table in TABLES:
                    cur.execute(DDL[table])

                # Limpa em ordem compatível com as chaves estrangeiras.
                for table in [
                    "financeiro_receitas",
                    "financeiro_despesas",
                    "financeiro_categorias",
                    "auditoria",
                    "usuarios",
                    "condominios",
                ]:
                    cur.execute(f"DELETE FROM {table}")

                for table in TABLES:
                    cols = sqlite_columns(sqlite_conn.cursor(), table)
                    if not cols:
                        continue

                    rows = sqlite_conn.execute(
                        f"SELECT {', '.join(cols)} FROM {table} ORDER BY id"
                    ).fetchall()

                    if not rows:
                        print(f"{table}: 0 registros")
                        continue

                    placeholders = ", ".join(["%s"] * len(cols))
                    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"

                    for row in rows:
                        cur.execute(sql, tuple(row[col] for col in cols))

                    print(f"{table}: {len(rows)} registros")

                # Reposiciona as sequências dos IDs para o próximo cadastro.
                for table in TABLES:
                    cur.execute(
                        """
                        SELECT setval(
                            pg_get_serial_sequence(%s, 'id'),
                            COALESCE((SELECT MAX(id) FROM """ + table + """), 1),
                            (SELECT COUNT(*) > 0 FROM """ + table + """)
                        )
                        """,
                        (table,),
                    )

            pg.commit()

        print()
        print("MIGRAÇÃO CONCLUÍDA COM SUCESSO.")

    finally:
        sqlite_conn.close()

if __name__ == "__main__":
    main()
