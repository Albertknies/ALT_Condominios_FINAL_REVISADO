from datetime import datetime, timedelta

from app import app, conn, init_db, save_condominio


base = {
    "cnpj": "",
    "unidades": "10",
    "sindicoTipo": "Morador",
    "sindico": "José",
    "cpfSindico": "12345678909",
    "unSindico": "101",
    "telSindico": "11988887777",
    "emailSindico": "jose@test.com",
    "endereco": {
        "rua": "Rua A",
        "numero": "1",
        "complemento": "",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "estado": "SP",
        "cep": "01000-000",
    },
    "conselheiros": [],
    "brigadistas": [],
    "conselho": "",
    "gas": "",
    "seg": "",
    "mercadinho": "",
    "juridico": "",
    "limpFis": "",
    "admFis": "",
    "ppci": "Sim",
    "ppciFis": "Sim",
    "ext": "Sim",
    "extFis": "Sim",
    "brig": "Sim",
    "qtdBrig": "2",
    "cxData": "",
    "segData": "",
    "dedData": "",
    "fimMandato": "",
    "validPpci": "",
    "recarga": "",
}


def make_date(days_from_today):
    return (datetime.now().date() + timedelta(days=days_from_today)).strftime("%Y-%m-%d")


items = [
    ("Condomínio Vencido", {
        "validPpci": make_date(-10),
        "recarga": make_date(-400),
        "cxData": make_date(-20),
        "fimMandato": make_date(-5),
        "segData": make_date(-30),
        "dedData": make_date(-15),
    }),
    ("Condomínio Próximo", {
        "validPpci": make_date(15),
        "recarga": make_date(20),
        "cxData": make_date(12),
        "fimMandato": make_date(18),
        "segData": make_date(10),
        "dedData": make_date(25),
    }),
    ("Condomínio Em Dia", {
        "validPpci": make_date(90),
        "recarga": make_date(-50),
        "cxData": make_date(60),
        "fimMandato": make_date(120),
        "segData": make_date(80),
        "dedData": make_date(70),
    }),
    ("Condomínio Recarga em 1 Ano", {
        "validPpci": make_date(90),
        "recarga": make_date(-330),
        "cxData": make_date(45),
        "fimMandato": make_date(200),
        "segData": make_date(100),
        "dedData": make_date(90),
    }),
]


with app.app_context():
    init_db()
    with conn() as c:
        c.execute("DELETE FROM condominios")
        c.commit()

    for nome, extras in items:
        payload = {**base, "nome": nome, **extras}
        cid = save_condominio(payload)
        print(f"Criado: {nome} (id={cid})")
