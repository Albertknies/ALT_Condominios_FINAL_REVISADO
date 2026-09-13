@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CRIAR_ATALHOS.ps1"
if errorlevel 1 (
  echo Nao foi possivel criar os atalhos.
  pause
  exit /b 1
)
echo Atalhos criados com o logo da ALT.
