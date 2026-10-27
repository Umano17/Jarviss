#!/bin/bash
cd "$HOME/jarvis" || exit 1
# Python del venv di Jarvis (senza «source activate»); se manca, quello di sistema
PY="$HOME/jarvis/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
"$PY" -c "import PIL" 2>/dev/null || "$PY" -m pip install -q pillow
(sleep 3 && (open -a "Google Chrome" "http://127.0.0.1:8765" || open "http://127.0.0.1:8765")) &
"$PY" avvio.py      # guardiano: avvia server.py, riavvia dopo gli aggiornamenti, torna indietro se qualcosa non va
