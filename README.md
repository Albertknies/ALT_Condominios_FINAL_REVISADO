# ALT — Gestão de Condomínios

Sistema Flask com cadastro de condomínios, alertas de vencimentos, demandas, financeiro, usuários, auditoria e relatórios PDF. Funciona com SQLite local ou PostgreSQL configurado por `DATABASE_URL`.

## Instalação e testes

No Windows, siga `LEIA-ME.txt` e execute `INSTALAR.bat`. Para desenvolvimento com Python 3.11 ou superior:

```sh
python -m venv .venv
# Ative o ambiente virtual antes dos comandos abaixo.
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Os testes usam SQLite temporário. Os testes do adaptador PostgreSQL usam mocks; não substituem validação com Neon real. A suíte gera PDFs na pasta ignorada `PDFs/`. O GitHub Actions executa a suíte em pushes e pull requests.

## Configuração online

- `DATABASE_URL`: conexão PostgreSQL.
- `ALT_SECRET_KEY`: segredo de sessão; obrigatório com `VERCEL=1`.
- `ALT_MASTER_USERNAME` e `ALT_MASTER_PASSWORD`: criação inicial do usuário master.
- `ALT_PORT`: porta local, padrão 47891.

Nunca versione senhas nem arquivos `.env`.

## Revisão inicial — outubro de 2026

Correções nesta revisão:

- Inserções em lote PostgreSQL passam pelo cursor do psycopg 3.
- Migração financeira também é executada no PostgreSQL.
- A coluna de vínculo de despesas com condomínio é criada nos bancos existentes sem remover registros. Despesas anteriores permanecem sem vínculo.
- Valores não finitos, excessivamente grandes e que arredondam para zero são rejeitados como erros de validação.
- Página de auditoria restaurada, com filtros e impressão.
- Teste dos filtros atualizado para os seletores do HTML atual.

Prioridades ainda abertas:

1. Eliminar a criação automática de `admin` com senha `admin`; em instalações existentes, alterar essa senha imediatamente e definir um fluxo seguro de primeiro acesso.
2. Revisar permissões de criação e exclusão, acesso por condomínio e revogação de sessões após troca de senha.
3. Completar o vínculo de despesas por condomínio no fluxo de cadastro/edição; a coluna sozinha não completa essa funcionalidade.
4. Criar backup completo com restauração testada. A exportação JSON atual inclui somente condomínios, sem financeiro, usuários, auditoria ou demandas. Arquivos em `/tmp` no Vercel são temporários.
5. Separar o arquivo `app.py` em módulos de cadastro, financeiro, autenticação e relatórios, depois de estabilizar os testes.
6. Verificar login, formulários e relatórios em celular e com PostgreSQL real antes de publicar.

Esta revisão prepara correções para avaliação em uma branch; não publica uma nova versão do sistema.


## Rotina operacional da administradora

- O início apresenta tarefas para hoje, atrasadas e aguardando retorno/aprovação, com atalhos para o acompanhamento.
- Vencimentos críticos abrem uma edição rápida do item, preservando os demais dados do cadastro. Datas de validade preenchidas explicitamente têm prioridade sobre o cálculo padrão.
- A atualização rápida usa bloqueio transacional e confere a versão do cadastro para evitar salvar por cima de uma alteração simultânea.
- Cada vencimento pode originar uma demanda com condomínio, responsável, prioridade e prazo. Se já existe uma demanda ativa para esse item, o sistema abre o acompanhamento existente.
- Demandas podem ser editadas e filtradas por situação, prazo, condomínio, responsável e busca textual. O filtro inicial mostra somente tarefas em aberto.
- Os estados Aguardando retorno e Aguardando aprovação ajudam a acompanhar dependências externas. Canceladas e concluídas não entram nos atrasos.
- Concluir a demanda não renova a validade: o atendimento e a atualização do cadastro são ações distintas, com acesso direto entre elas.
- A auditoria registra criação de tarefas, mudanças de prazo/responsável/status e atualização de validade.

A atualização do banco acrescenta `origem_campo` e `origem_data` às demandas, além de um índice de consulta. Não remove registros existentes. O sistema não armazena documentos de condomínio e não envia notificações automáticas nesta versão.
