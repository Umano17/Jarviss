#!/bin/bash
# Installa il custode di Jarvis (3.8): parte da solo al login del Mac e resta sempre acceso.
# Doppio clic una volta sola. Per toglierlo: launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/it.jarvis.custode.plist
cd "$HOME/jarvis" || { echo "Non trovo la cartella ~/jarvis"; exit 1; }
mkdir -p dati "$HOME/Library/LaunchAgents"

PY=/usr/bin/python3
if [ -x venv/bin/python3 ] && venv/bin/python3 -c "import sys" 2>/dev/null; then PY="$HOME/jarvis/venv/bin/python3"; fi
"$PY" -c "import sys; assert sys.version_info >= (3, 9)" || { echo "Serve Python 3.9 o più recente"; exit 1; }

PLIST="$HOME/Library/LaunchAgents/it.jarvis.custode.plist"
cat > "$PLIST" <<FINE
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>it.jarvis.custode</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$HOME/jarvis/custode.py</string></array>
  <key>WorkingDirectory</key><string>$HOME/jarvis</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>20</integer>
  <key>StandardOutPath</key><string>$HOME/jarvis/dati/custode.log</string>
  <key>StandardErrorPath</key><string>$HOME/jarvis/dati/custode.log</string>
</dict></plist>
FINE

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "✅ Custode installato e avviato (si riavvia da solo al login)."
sleep 3
curl -s -o /dev/null -w "Pagina locale: http://127.0.0.1:8766 → risposta %{http_code}\n" http://127.0.0.1:8766/

TS=$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)
if [ -x "$TS" ]; then
  "$TS" serve --bg --https=8443 http://127.0.0.1:8766 && echo "✅ Tailscale: la pagina è sull'indirizzo del Mac, porta 8443 (solo nella tua rete Tailscale)."
  "$TS" serve status 2>/dev/null | head -12
else
  echo "⚠️ Tailscale non trovato: installalo e poi esegui  tailscale serve --bg --https=8443 http://127.0.0.1:8766"
fi
grep -q '^JARVIS_PIN=..*' .env 2>/dev/null || echo "⚠️ Manca JARVIS_PIN nel .env: senza PIN la pagina da fuori resta chiusa."
echo
echo "Ricorda: Impostazioni di Sistema → Batteria/Risparmio energia → impedisci lo stop automatico con l'alimentatore."
