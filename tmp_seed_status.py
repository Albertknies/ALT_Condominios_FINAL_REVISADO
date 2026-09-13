from app import conn, save_condominio, init_db, load_data, get_condominio_alert_status
import datetime
from werkzeug.security import generate_password_hash

init_db()
with conn() as c:
    c.execute("INSERT OR IGNORE INTO usuarios(username, password_hash, role) VALUES(?,?,?)", ("admin", generate_password_hash("admin"), "admin"))
    c.commit()

t = datetime.date.today()
base = {
    "cnpj": "",
    "unidades": "10",
    "sindicoTipo": "Morador",
    "sindico": "José",
    "cpfSindico": "12345678909",
    "unSindico": "101",
    "telSindico": "11988887777",
    "emailSindico": "jose@test.com",
    "endereco": {"rua": "Rua A", "numero": "1", "complemento": "", "bairro": "Centro", "cidade": "São Paulo", "estado": "SP", "cep": "01000-000"},
    "conselheiros": [],
    "brigadistas": [],
    "conselho": "",
    "gas": "",
    "seg": "",
    "mercadinho": "",
    "juridico": "",
    "limpFis": "",
    "admFis": "",
    "recarga": (t + datetime.timedelta(days=50)).strftime("%Y-%m-%d"),
    "cxData": (t + datetime.timedelta(days=50)).strftime("%Y-%m-%d"),
    "fimMandato": (t + datetime.timedelta(days=50)).strftime("%Y-%m-%d"),
}

ids = []
ids.append(save_condominio({**base, "nome": "Condomínio Vencido", "validPpci": (t - datetime.timedelta(days=2)).strftime("%Y-%m-%d")}))
ids.append(save_condominio({**base, "nome": "Condomínio Próximo", "validPpci": (t + datetime.timedelta(days=15)).strftime("%Y-%m-%d")}))
ids.append(save_condominio({**base, "nome": "Condomínio Em Dia", "validPpci": (t + datetime.timedelta(days=45)).strftime("%Y-%m-%d")}))

with conn() as c:
    rows = c.execute("SELECT nome, dados_json FROM condominios WHERE nome IN (?, ?, ?) ORDER BY nome COLLATE NOCASE", ("Condomínio Vencido", "Condomínio Próximo", "Condomínio Em Dia")).fetchall()
    for r in rows:
        d = load_data(r)
        status = get_condominio_alert_status(d)
        print(r["nome"], status["level"], status["red_count"], status["yellow_count"], status["green_count"])

print("ids", ids)
