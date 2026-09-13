# ALT — Sistema de Cadastro de Condomínios

Sistema local para Windows com backend Flask/Waitress + banco SQLite.

## Revisões principais
- Servidor restrito a 127.0.0.1 e porta local 47891.
- Launcher silencioso com pythonw.exe: nenhuma janela CMD durante o uso normal.
- Verificação de saúde antes de iniciar o servidor, evitando múltiplas cópias.
- Edge/Chrome podem abrir o sistema em modo aplicativo.
- Ícone e favicon da ALT.
- Proteção CSRF nos formulários POST.
- Validação de datas, inteiros, e-mail e opções Sim/Não.
- Limpeza de campos dependentes quando a resposta principal é Não.
- Lógica de gás separando Ultragás e Administradora.
- Brigadistas dinâmicos sem perder os dados já digitados ao alterar a quantidade.
- Backup manual em JSON e snapshots automáticos do banco.
- Importação limitada e transacional para evitar importações parciais.
- PDFs salvos automaticamente em uma estrutura de pastas por condomínio e data.
- Escape de conteúdo do usuário no PDF para evitar quebra por caracteres especiais.
- SQL parametrizado.
- Limite de upload de 10 MB.
- Não há exposição direta para a rede local.

## Instalação
1. Instale Python 3.11+.
2. Execute `INSTALAR.bat`.
3. Execute `CRIAR_ATALHOS.bat`.
4. Use o atalho `ALT Gestão de Condomínios`.

## Backup
Use `Exportar backup` regularmente. Os backups automáticos ficam na pasta `backups`.

## PDF
O PDF é salvo em `PDFs\NomeDoCondominio\AAAA-MM-DD\` e também é enviado para o navegador.

## Segurança
O projeto é destinado a uso local em um PC. Não publique o servidor na internet. Para uso multiusuário, será necessário autenticação, HTTPS, permissões, banco servidor e infraestrutura apropriada.
