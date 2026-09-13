@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   ALT GESTAO DE CONDOMINIOS - INSTALACAO
echo ============================================
echo.

where py >nul 2>&1
if not errorlevel 1 goto :PYLAUNCHER
where python >nul 2>&1
if not errorlevel 1 goto :PYTHON

echo ERRO: Python 3.11 ou superior nao foi encontrado.
echo Instale o Python pelo site oficial e marque a opcao para adicionar ao PATH.
echo.
pause
exit /b 1

:PYLAUNCHER
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 (
  echo ERRO: Python 3.11 ou superior e necessario.
  pause
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 goto :VENVERROR
goto :INSTALL

:PYTHON
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 (
  echo ERRO: Python 3.11 ou superior e necessario.
  pause
  exit /b 1
)
python -m venv .venv
if errorlevel 1 goto :VENVERROR

goto :INSTALL

:INSTALL
if not exist ".venv\Scripts\python.exe" goto :VENVERROR
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :PIPERROR
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :PIPERROR

echo.
echo Instalacao concluida com sucesso.
echo Agora execute INICIAR.bat ou CRIAR_ATALHOS.bat.
echo.
pause
exit /b 0

:VENVERROR
echo ERRO: nao foi possivel criar o ambiente do sistema.
pause
exit /b 1

:PIPERROR
echo ERRO: nao foi possivel instalar os componentes.
echo Verifique sua internet e tente novamente.
pause
exit /b 1
