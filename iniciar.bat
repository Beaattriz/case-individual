@echo off
chcp 65001 >nul
REM Painel Folia - cria o ambiente, instala o Flask e liga o servidor.
REM Uso: duplo clique neste arquivo (ou "iniciar.bat" no terminal).

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERRO: nao encontrei o Python. Instale o Python 3 e tente de novo.
        pause
        exit /b 1
    )
)

echo Instalando dependencias (Flask) ...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 (
    echo.
    echo ERRO: nao foi possivel instalar o Flask. Verifique a internet.
    pause
    exit /b 1
)

echo.
echo Abra http://127.0.0.1:5000 no navegador. Para desligar: Ctrl+C
echo.
".venv\Scripts\python.exe" backend\app.py
pause
