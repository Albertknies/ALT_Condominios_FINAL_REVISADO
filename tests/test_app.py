import re
import tempfile
import unittest
from pathlib import Path
import shutil

from app import app, conn, create_user, init_db, save_condominio, authenticate_user, get_condominio_alert_status, build_report_rows, get_finance_summary


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-key'
        self.temp_dir = tempfile.mkdtemp(prefix="alt-tests-")
        app.config['DATABASE'] = str(Path(self.temp_dir) / 'alt-test.db')
        self.client = app.test_client()
        init_db()
        with conn() as c:
            c.execute('DELETE FROM auditoria')
            c.execute('DELETE FROM usuarios')
            c.execute('DELETE FROM condominios')
            c.execute(
                'INSERT INTO usuarios(username, password_hash, role) VALUES(?,?,?)',
                ('admin', __import__('werkzeug.security').security.generate_password_hash('admin'), 'admin'),
            )
            c.commit()

    def tearDown(self):
        app.config.pop('DATABASE', None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_root_page_redirects_to_login_when_not_authenticated(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_login_and_export_are_recorded_in_audit(self):
        login_response = self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        self.assertEqual(login_response.status_code, 200)
        self.assertIn('Condomínios', login_response.get_data(as_text=True))

        cid = save_condominio({
            'nome': 'Condomínio teste',
            'cnpj': '', 'unidades': '10', 'sindicoTipo': 'Morador', 'sindico': 'José', 'cpfSindico': '12345678909',
            'unSindico': '101', 'telSindico': '11988887777', 'emailSindico': 'jose@test.com', 'endereco': {'rua': 'Rua A', 'numero': '1', 'complemento': '', 'bairro': 'Centro', 'cidade': 'São Paulo', 'estado': 'SP', 'cep': '01000-000'},
            'conselheiros': [], 'brigadistas': [], 'conselho': '', 'gas': '', 'seg': '', 'mercadinho': '', 'juridico': '', 'limpFis': '', 'admFis': ''
        })
        pdf_response = self.client.get(f'/pdf/{cid}?visualizar=1')
        self.assertEqual(pdf_response.status_code, 200)

        with conn() as c:
            rows = c.execute('SELECT action, username FROM auditoria WHERE action IN (?, ?) ORDER BY id DESC', ('pdf', 'exportar_json')).fetchall()
        self.assertTrue(any(row['action'] == 'pdf' and row['username'] == 'admin' for row in rows))

    def test_admin_can_manage_users(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)

        page = self.client.get('/usuarios')
        content = page.get_data(as_text=True)
        token = re.findall(r'name="csrf_token"\s+value="([^"]+)"', content)[0]

        create_response = self.client.post('/usuarios/criar', data={'csrf_token': token, 'username': 'usuario1', 'password': '123456', 'password_confirm': '123456', 'role': 'normal'}, follow_redirects=True)
        self.assertEqual(create_response.status_code, 200)
        self.assertIn('usuario1', create_response.get_data(as_text=True))

        with conn() as c:
            row = c.execute('SELECT username, role FROM usuarios WHERE username=?', ('usuario1',)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['role'], 'normal')

        user = authenticate_user('usuario1', '123456')
        self.assertIsNotNone(user)

        page2 = self.client.get('/usuarios')
        content2 = page2.get_data(as_text=True)
        csrf_tokens = re.findall(r'name="csrf_token"\s+value="([^"]+)"', content2)
        token2 = csrf_tokens[-1]

        with conn() as c:
            user_id = c.execute('SELECT id FROM usuarios WHERE username=?', ('usuario1',)).fetchone()['id']

        reset_response = self.client.post(f'/usuarios/{user_id}/resetar-senha', data={'csrf_token': token2, 'new_password': 'nova123', 'new_password_confirm': 'nova123'}, follow_redirects=True)
        self.assertEqual(reset_response.status_code, 200)
        self.assertIsNotNone(authenticate_user('usuario1', 'nova123'))

    def test_admin_can_change_own_username_and_password(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)

        page = self.client.get('/usuarios')
        content = page.get_data(as_text=True)
        token = re.findall(r'name="csrf_token"\s+value="([^"]+)"', content)[0]

        with conn() as c:
            user_id = c.execute('SELECT id FROM usuarios WHERE username=?', ('admin',)).fetchone()['id']

        response = self.client.post(
            f'/usuarios/{user_id}/editar',
            data={'csrf_token': token, 'username': 'superadmin', 'password': 'novaSenha123', 'password_confirm': 'novaSenha123'},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('superadmin', response.get_data(as_text=True))
        self.assertIsNotNone(authenticate_user('superadmin', 'novaSenha123'))
        self.assertIsNone(authenticate_user('admin', 'admin'))

    def test_finance_role_is_supported(self):
        user = create_user('financeiro', 'financeiro123', 'financeiro', 'financeiro123')
        self.assertEqual(user, 'financeiro')
        self.assertIsNotNone(authenticate_user('financeiro', 'financeiro123'))

    def test_finance_user_can_access_financial_dashboard_but_not_admin_area(self):
        create_user('financeiro', 'financeiro123', 'financeiro', 'financeiro123')
        login_response = self.client.post('/login', data={'username': 'financeiro', 'password': 'financeiro123'}, follow_redirects=True)
        self.assertEqual(login_response.status_code, 200)
        self.assertIn('Financeiro', login_response.get_data(as_text=True))

        dashboard = self.client.get('/financeiro')
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('Painel financeiro', dashboard.get_data(as_text=True))

        users_page = self.client.get('/usuarios', follow_redirects=True)
        self.assertEqual(users_page.status_code, 200)
        self.assertIn('não tem acesso administrativo', users_page.get_data(as_text=True))

    def test_only_master_user_can_access_import_and_export(self):
        admin_login = self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        self.assertEqual(admin_login.status_code, 200)
        self.assertEqual(self.client.get('/importar', follow_redirects=True).status_code, 200)
        self.assertIn('Apenas o usuário master', self.client.get('/exportar-json', follow_redirects=True).get_data(as_text=True))

        create_user('albert', 'senha-segura', 'master', 'senha-segura')
        self.client.get('/logout')
        master_login = self.client.post('/login', data={'username': 'albert', 'password': 'senha-segura'}, follow_redirects=True)
        self.assertEqual(master_login.status_code, 200)
        self.assertEqual(self.client.get('/importar').status_code, 200)
        self.assertEqual(self.client.get('/exportar-json').status_code, 200)

    def test_finance_user_can_create_category_and_view_summary(self):
        create_user('financeiro', 'financeiro123', 'financeiro', 'financeiro123')
        self.client.post('/login', data={'username': 'financeiro', 'password': 'financeiro123'}, follow_redirects=True)

        categories_page = self.client.get('/financeiro/categorias')
        content = categories_page.get_data(as_text=True)
        token = re.findall(r'name="csrf_token"\s+value="([^"]+)"', content)[0]

        create_response = self.client.post('/financeiro/categorias/salvar', data={
            'csrf_token': token,
            'nome': 'Condomínio',
            'tipo': 'receita',
            'descricao': 'Receitas de mensalidades',
        }, follow_redirects=True)
        self.assertEqual(create_response.status_code, 200)
        self.assertIn('Condomínio', create_response.get_data(as_text=True))

        categories_page_after = self.client.get('/financeiro/categorias')
        self.assertEqual(categories_page_after.status_code, 200)
        self.assertIn('Condomínio', categories_page_after.get_data(as_text=True))

        summary_page = self.client.get('/financeiro/resumo-categoria')
        self.assertEqual(summary_page.status_code, 200)
        self.assertIn('Resumo por categoria', summary_page.get_data(as_text=True))

    def test_normal_user_cannot_access_financial_dashboard(self):
        create_user('usuario1', '123456', 'normal', '123456')
        self.client.post('/login', data={'username': 'usuario1', 'password': '123456'}, follow_redirects=True)

        response = self.client.get('/financeiro', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('não tem acesso financeiro', response.get_data(as_text=True))

    def test_login_page_does_not_show_default_admin_credentials(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('admin / admin', response.get_data(as_text=True).lower())
        self.assertNotIn('usuário padrão', response.get_data(as_text=True).lower())

    def test_admin_can_export_monthly_audit_pdf(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        response = self.client.get('/auditoria/exportar-pdf?mes=2026-09', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response.headers.get('Content-Type', ''))
        self.assertTrue(response.data.startswith(b'%PDF'))

    def test_authenticated_user_can_export_project_summary_pdf(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        response = self.client.get('/relatorio-projeto')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response.headers.get('Content-Type', ''))
        self.assertTrue(response.data.startswith(b'%PDF'))

    def test_admin_can_view_audit_log(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        response = self.client.get('/auditoria')
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn('Relatório de acesso', content)
        self.assertIn('login', content.lower())

    def test_audit_report_has_direct_print_action(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        response = self.client.get('/auditoria')
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn('Imprimir PDF', content)
        self.assertIn('window.print()', content)

    def test_users_page_shows_only_user_management(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        with conn() as c:
            c.execute('INSERT INTO auditoria(username, action, details, created_at) VALUES(?,?,?,?)', ('admin', 'editar_usuario', 'Usuário admin atualizado por admin', '2026-09-10T10:30:00'))
            c.execute('INSERT INTO auditoria(username, action, details, created_at) VALUES(?,?,?,?)', ('admin', 'login', 'Usuário admin entrou no sistema.', '2026-09-10T11:00:00'))
            c.commit()

        response = self.client.get('/usuarios')
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn('Usuários cadastrados', content)
        self.assertNotIn('Últimas movimentações', content)
        self.assertNotIn('editar_usuario', content.lower())
        self.assertNotIn('exportar_auditoria_pdf', content.lower())

    def test_condominio_alert_status_is_calculated_by_deadline(self):
        today = __import__('datetime').datetime.now().date()
        expired = (today - __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d')
        soon = (today + __import__('datetime').timedelta(days=15)).strftime('%Y-%m-%d')
        ok = (today + __import__('datetime').timedelta(days=45)).strftime('%Y-%m-%d')
        recarga_expired = (today - __import__('datetime').timedelta(days=370)).strftime('%Y-%m-%d')
        recarga_soon = (today - __import__('datetime').timedelta(days=340)).strftime('%Y-%m-%d')
        recarga_ok = (today - __import__('datetime').timedelta(days=100)).strftime('%Y-%m-%d')

        self.assertEqual(get_condominio_alert_status({'validPpci': expired, 'recarga': recarga_expired, 'cxData': ok, 'fimMandato': ok})['level'], 'red')
        self.assertEqual(get_condominio_alert_status({'validPpci': soon, 'recarga': recarga_soon, 'cxData': ok, 'fimMandato': ok})['level'], 'yellow')
        self.assertEqual(get_condominio_alert_status({'validPpci': ok, 'recarga': recarga_ok, 'cxData': ok, 'fimMandato': ok})['level'], 'green')

    def test_alert_summary_counts_red_yellow_and_green_statuses(self):
        today = __import__('datetime').datetime.now().date()
        expired = (today - __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d')
        soon = (today + __import__('datetime').timedelta(days=15)).strftime('%Y-%m-%d')
        ok = (today + __import__('datetime').timedelta(days=45)).strftime('%Y-%m-%d')
        recarga_expired = (today - __import__('datetime').timedelta(days=370)).strftime('%Y-%m-%d')
        recarga_soon = (today - __import__('datetime').timedelta(days=340)).strftime('%Y-%m-%d')
        recarga_ok = (today - __import__('datetime').timedelta(days=100)).strftime('%Y-%m-%d')

        statuses = [
            get_condominio_alert_status({'validPpci': expired, 'recarga': recarga_expired, 'cxData': ok, 'fimMandato': ok}),
            get_condominio_alert_status({'validPpci': soon, 'recarga': recarga_soon, 'cxData': ok, 'fimMandato': ok}),
            get_condominio_alert_status({'validPpci': ok, 'recarga': recarga_ok, 'cxData': ok, 'fimMandato': ok}),
        ]

        self.assertEqual([item['level'] for item in statuses], ['red', 'yellow', 'green'])

    def test_due_today_is_treated_as_red_and_not_yellow(self):
        today = __import__('datetime').datetime.now().date()
        due_today = today.strftime('%Y-%m-%d')
        last_recarga = (today - __import__('datetime').timedelta(days=365)).strftime('%Y-%m-%d')

        status = get_condominio_alert_status({'validPpci': due_today, 'recarga': last_recarga, 'cxData': due_today, 'fimMandato': due_today})
        self.assertEqual(status['level'], 'red')
        self.assertEqual(status['red_count'], 3)

    def test_extinguisher_reload_is_evaluated_after_one_year(self):
        today = __import__('datetime').datetime.now().date()
        recarga = (today - __import__('datetime').timedelta(days=300)).strftime('%Y-%m-%d')

        status = get_condominio_alert_status({'recarga': recarga})
        issue = next(issue for issue in status['issues'] if issue['label'] == 'Recarga de extintor')

        self.assertEqual(status['level'], 'green')
        self.assertEqual(issue['days_left'], 65)
        self.assertEqual(issue['days_left_label'], 'vence em 65 dias')

    def test_alert_status_includes_policy_water_and_dedetizacao_deadlines_with_days_left(self):
        today = __import__('datetime').datetime.now().date()
        soon = (today + __import__('datetime').timedelta(days=12)).strftime('%Y-%m-%d')
        seg_expired = (today - __import__('datetime').timedelta(days=370)).strftime('%Y-%m-%d')
        ded_expired = (today - __import__('datetime').timedelta(days=200)).strftime('%Y-%m-%d')
        recarga = (today - __import__('datetime').timedelta(days=340)).strftime('%Y-%m-%d')

        status = get_condominio_alert_status({
            'validPpci': soon,
            'segData': seg_expired,
            'cxData': soon,
            'dedData': ded_expired,
            'fimMandato': soon,
            'recarga': recarga
        })

        self.assertEqual(status['level'], 'red')
        self.assertIn('Validade do PPCI', [issue['label'] for issue in status['issues']])
        self.assertIn('Seguro predial', [issue['label'] for issue in status['issues']])
        self.assertIn('Limpeza da caixa d\'água', [issue['label'] for issue in status['issues']])
        self.assertIn('Dedetização', [issue['label'] for issue in status['issues']])
        self.assertTrue(any(issue['days_left'] == 12 for issue in status['issues'] if issue['label'] == 'Validade do PPCI'))

    def test_dedetizacao_uses_six_month_deadline(self):
        today = __import__('datetime').datetime.now().date()
        last_dedetizacao = (today - __import__('datetime').timedelta(days=200)).strftime('%Y-%m-%d')

        status = get_condominio_alert_status({'dedData': last_dedetizacao})
        issue = next(issue for issue in status['issues'] if issue['label'] == 'Dedetização')

        self.assertEqual(issue['status'], 'red')
        self.assertTrue(issue['days_left'] < 0)
        self.assertIn('Vencido', issue['date_label'])

    def test_report_rows_show_expiration_date_and_condo_name(self):
        today = __import__('datetime').datetime.now().date()
        expired = (today - __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d')

        with conn() as c:
            c.execute('DELETE FROM condominios')
            c.execute('INSERT INTO condominios(nome, atualizado_em, dados_json) VALUES(?,?,?)', ('Condomínio Teste Relatório', today.isoformat(), __import__('json').dumps({
                'nome': 'Condomínio Teste Relatório',
                'validPpci': expired,
                'recarga': (today + __import__('datetime').timedelta(days=10)).strftime('%Y-%m-%d'),
                'cxData': (today + __import__('datetime').timedelta(days=30)).strftime('%Y-%m-%d'),
                'fimMandato': (today + __import__('datetime').timedelta(days=50)).strftime('%Y-%m-%d'),
                'segData': (today + __import__('datetime').timedelta(days=50)).strftime('%Y-%m-%d'),
                'dedData': (today + __import__('datetime').timedelta(days=50)).strftime('%Y-%m-%d'),
            })))
            c.commit()

        rows = build_report_rows('vencidos')
        self.assertTrue(any(row['nome'] == 'Condomínio Teste Relatório' and 'Vencido' in row['data'] for row in rows))

    def test_report_routes_generate_pdf_for_due_statuses(self):
        today = __import__('datetime').datetime.now().date()
        expired = (today - __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d')
        soon = (today + __import__('datetime').timedelta(days=15)).strftime('%Y-%m-%d')
        ok = (today + __import__('datetime').timedelta(days=45)).strftime('%Y-%m-%d')

        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        save_condominio({
            'nome': 'Condomínio Atrasado',
            'cnpj': '', 'unidades': '10', 'sindicoTipo': 'Morador', 'sindico': 'José', 'cpfSindico': '12345678909',
            'unSindico': '101', 'telSindico': '11988887777', 'emailSindico': 'jose@test.com', 'endereco': {'rua': 'Rua A', 'numero': '1', 'complemento': '', 'bairro': 'Centro', 'cidade': 'São Paulo', 'estado': 'SP', 'cep': '01000-000'},
            'conselheiros': [], 'brigadistas': [], 'conselho': '', 'validPpci': expired, 'recarga': ok, 'cxData': ok, 'fimMandato': ok,
            'gas': '', 'seg': '', 'mercadinho': '', 'juridico': '', 'limpFis': '', 'admFis': ''
        })
        save_condominio({
            'nome': 'Condomínio Próximo',
            'cnpj': '', 'unidades': '20', 'sindicoTipo': 'Morador', 'sindico': 'Maria', 'cpfSindico': '11144477735',
            'unSindico': '202', 'telSindico': '11977776666', 'emailSindico': 'maria@test.com', 'endereco': {'rua': 'Rua B', 'numero': '2', 'complemento': '', 'bairro': 'Jardim', 'cidade': 'São Paulo', 'estado': 'SP', 'cep': '02000-000'},
            'conselheiros': [], 'brigadistas': [], 'conselho': '', 'validPpci': soon, 'recarga': ok, 'cxData': ok, 'fimMandato': ok,
            'gas': '', 'seg': '', 'mercadinho': '', 'juridico': '', 'limpFis': '', 'admFis': ''
        })
        save_condominio({
            'nome': 'Condomínio Em Dia',
            'cnpj': '', 'unidades': '30', 'sindicoTipo': 'Morador', 'sindico': 'Paulo', 'cpfSindico': '22233344455',
            'unSindico': '303', 'telSindico': '11966665555', 'emailSindico': 'paulo@test.com', 'endereco': {'rua': 'Rua C', 'numero': '3', 'complemento': '', 'bairro': 'Vila', 'cidade': 'São Paulo', 'estado': 'SP', 'cep': '03000-000'},
            'conselheiros': [], 'brigadistas': [], 'conselho': '', 'validPpci': ok, 'recarga': ok, 'cxData': ok, 'fimMandato': ok,
            'gas': '', 'seg': '', 'mercadinho': '', 'juridico': '', 'limpFis': '', 'admFis': ''
        })

        for param in ('vencidos', 'vai-vencer', 'em-dia'):
            response = self.client.get(f'/relatorio?tipo={param}')
            self.assertEqual(response.status_code, 200)
            self.assertIn('application/pdf', response.headers.get('Content-Type', ''))
            self.assertTrue(response.data.startswith(b'%PDF'))

    def test_index_page_has_status_filters_and_marker_classes(self):
        self.client.post('/login', data={'username': 'admin', 'password': 'admin'}, follow_redirects=True)
        response = self.client.get('/')
        content = response.get_data(as_text=True)

        self.assertIn('data-filter-status', content)
        self.assertIn('filter-pill', content)
        self.assertIn('alert-red', content)
        self.assertIn('alert-yellow', content)
        self.assertIn('alert-green', content)

    def test_finance_user_can_register_income_and_recurring_expenses(self):
        create_user('financeiro', 'financeiro123', 'financeiro', 'financeiro123')
        self.client.post('/login', data={'username': 'financeiro', 'password': 'financeiro123'}, follow_redirects=True)

        cid = save_condominio({
            'nome': 'Condomínio ALT Financeiro',
            'cnpj': '', 'unidades': '20', 'sindicoTipo': 'Morador', 'sindico': 'Carlos', 'cpfSindico': '12345678909',
            'unSindico': '201', 'telSindico': '11900001111', 'emailSindico': 'carlos@test.com', 'endereco': {'rua': 'Rua Financeira', 'numero': '1', 'complemento': '', 'bairro': 'Centro', 'cidade': 'São Paulo', 'estado': 'SP', 'cep': '01000-000'},
            'conselheiros': [], 'brigadistas': [], 'conselho': '', 'gas': '', 'seg': '', 'mercadinho': '', 'juridico': '', 'limpFis': '', 'admFis': '', 'banco': '', 'agencia': '', 'conta': ''
        })

        page = self.client.get('/financeiro')
        token = re.findall(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True))[0]

        receita = self.client.post('/financeiro/receitas/salvar', data={
            'csrf_token': token,
            'condominio_id': str(cid),
            'valor': '1500.00',
            'mes_referencia': '2026-09',
            'observacao': 'Pagamento mensal do condomínio'
        }, follow_redirects=True)
        self.assertEqual(receita.status_code, 200)
        self.assertIn('receita', receita.get_data(as_text=True).lower())

        despesa = self.client.post('/financeiro/despesas/salvar', data={
            'csrf_token': token,
            'nome': 'Internet',
            'valor': '350.00',
            'vencimento': '2026-09-10',
            'parcelas': '3',
            'mes_referencia': '2026-09',
            'observacao': 'Plano de internet'
        }, follow_redirects=True)
        self.assertEqual(despesa.status_code, 200)
        self.assertIn('internet', despesa.get_data(as_text=True).lower())

        with conn() as c:
            receita_rows = c.execute('SELECT COUNT(*) AS total FROM financeiro_receitas WHERE condominio_id = ?', (cid,)).fetchone()['total']
            despesa_rows = c.execute('SELECT COUNT(*) AS total FROM financeiro_despesas WHERE nome = ?', ('Internet',)).fetchone()['total']
            self.assertEqual(receita_rows, 1)
            self.assertEqual(despesa_rows, 3)

        dashboard = self.client.get('/financeiro')
        self.assertEqual(dashboard.status_code, 200)
        page = dashboard.get_data(as_text=True)
        self.assertIn('Receita', page)
        self.assertIn('Despesa', page)
        self.assertIn('Saldo', page)

    def test_finance_report_pdf_contains_summary_values(self):
        create_user('financeiro', 'financeiro123', 'financeiro', 'financeiro123')
        self.client.post('/login', data={'username': 'financeiro', 'password': 'financeiro123'}, follow_redirects=True)

        cid = save_condominio({
            'nome': 'Condomínio ALT Relatório',
            'cnpj': '', 'unidades': '15', 'sindicoTipo': 'Morador', 'sindico': 'Ana', 'cpfSindico': '12345678909',
            'unSindico': '101', 'telSindico': '11911112222', 'emailSindico': 'ana@test.com', 'endereco': {'rua': 'Rua Relatório', 'numero': '7', 'complemento': '', 'bairro': 'Centro', 'cidade': 'São Paulo', 'estado': 'SP', 'cep': '01000-000'},
            'conselheiros': [], 'brigadistas': [], 'conselho': '', 'gas': '', 'seg': '', 'mercadinho': '', 'juridico': '', 'limpFis': '', 'admFis': '', 'banco': '', 'agencia': '', 'conta': ''
        })

        page = self.client.get('/financeiro')
        token = re.findall(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True))[0]
        self.client.post('/financeiro/receitas/salvar', data={'csrf_token': token, 'condominio_id': str(cid), 'valor': '800.00', 'mes_referencia': '2026-09', 'observacao': 'Relatório'})
        self.client.post('/financeiro/despesas/salvar', data={'csrf_token': token, 'nome': 'Energia', 'valor': '250.00', 'vencimento': '2026-09-15', 'parcelas': '1', 'mes_referencia': '2026-09', 'observacao': 'Energia'})

        response = self.client.get('/financeiro/relatorio?mes=2026-09')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response.headers.get('Content-Type', ''))
        self.assertTrue(response.data.startswith(b'%PDF'))

    def test_finance_summary_filters_income_and_expenses_by_date_range(self):
        with conn() as c:
            c.execute("INSERT INTO financeiro_receitas(grupo, valor, data_pagamento, mes_referencia) VALUES(?,?,?,?)", ("ALT", 100, "2026-09-05", "2026-09"))
            c.execute("INSERT INTO financeiro_receitas(grupo, valor, data_pagamento, mes_referencia) VALUES(?,?,?,?)", ("ALT", 900, "2026-10-05", "2026-10"))
            c.execute("INSERT INTO financeiro_despesas(nome, valor, vencimento, mes_referencia) VALUES(?,?,?,?)", ("Internet", 40, "2026-09-20", "2026-09"))
            c.execute("INSERT INTO financeiro_despesas(nome, valor, vencimento, mes_referencia) VALUES(?,?,?,?)", ("Aluguel", 500, "2026-10-01", "2026-10"))
            c.commit()

        summary = get_finance_summary("2026-09", "2026-09-01", "2026-09-30")

        self.assertEqual(summary["receita"], 100)
        self.assertEqual(summary["despesa"], 40)
        self.assertEqual(summary["saldo"], 60)
        self.assertEqual(summary["data_inicio"], "2026-09-01")
        self.assertEqual(summary["data_fim"], "2026-09-30")

    def test_finance_tabs_filter_records_by_period_and_can_delete_them(self):
        create_user('financeiro', 'financeiro123', 'financeiro', 'financeiro123')
        self.client.post('/login', data={'username': 'financeiro', 'password': 'financeiro123'}, follow_redirects=True)

        page = self.client.get('/financeiro')
        token = re.findall(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True))[0]
        self.client.post('/financeiro/receitas/salvar', data={
            'csrf_token': token,
            'valor': '100.00',
            'mes_referencia': '2026-08',
            'categoria': 'Mensalidade',
        })
        self.client.post('/financeiro/despesas/salvar', data={
            'csrf_token': token,
            'nome': 'Energia antiga',
            'valor': '80.00',
            'vencimento': '2026-08-10',
            'parcelas': '1',
            'mes_referencia': '2026-08',
        })
        self.client.post('/financeiro/categorias/salvar', data={
            'csrf_token': token,
            'nome': 'Categoria antiga',
            'tipo': 'despesa',
        })

        dashboard = self.client.get('/financeiro?mes=2026-09')
        content = dashboard.get_data(as_text=True)
        self.assertIn('Nenhuma receita no período selecionado.', content)
        self.assertIn('Nenhuma despesa no período selecionado.', content)
        self.assertIn('Categoria antiga', content)

        with conn() as c:
            receita_id = c.execute("SELECT id FROM financeiro_receitas WHERE categoria = 'Mensalidade'").fetchone()['id']
            despesa_id = c.execute("SELECT id FROM financeiro_despesas WHERE nome = 'Energia antiga'").fetchone()['id']
            categoria_id = c.execute("SELECT id FROM financeiro_categorias WHERE nome = 'Categoria antiga'").fetchone()['id']

        self.assertEqual(self.client.post(f'/financeiro/receitas/{receita_id}/excluir?mes=2026-09', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.client.post(f'/financeiro/despesas/{despesa_id}/excluir?mes=2026-09', data={'csrf_token': token}).status_code, 302)
        self.assertEqual(self.client.post(f'/financeiro/categorias/{categoria_id}/excluir?mes=2026-09', data={'csrf_token': token}).status_code, 302)

        with conn() as c:
            self.assertIsNone(c.execute('SELECT id FROM financeiro_receitas WHERE id = ?', (receita_id,)).fetchone())
            self.assertIsNone(c.execute('SELECT id FROM financeiro_despesas WHERE id = ?', (despesa_id,)).fetchone())
            self.assertIsNone(c.execute('SELECT id FROM financeiro_categorias WHERE id = ?', (categoria_id,)).fetchone())


if __name__ == "__main__":
    unittest.main()
