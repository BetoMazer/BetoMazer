@echo off
REM Duplo clique para abrir o painel (Windows). Requer Python 3.10+ instalado.
cd /d %~dp0
python -m pip install -q -r requirements.txt
start "" http://localhost:8050
python -m eleicoes.painel %*
pause
