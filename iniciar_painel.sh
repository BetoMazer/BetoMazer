#!/usr/bin/env bash
# Abre o painel (macOS/Linux). Uso: ./iniciar_painel.sh   ou   ./iniciar_painel.sh --demo
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
( sleep 2; (command -v open >/dev/null && open http://localhost:8050) || xdg-open http://localhost:8050 ) >/dev/null 2>&1 &
python3 -m eleicoes.painel "$@"
