# Jarvis 3.8 – Pagina iPhone e accensione a distanza

## Cosa cambia

| Novità | Dove | Come si usa |
|---|---|---|
| **Custode** | `custode.py`, `installa_custode.command` | Programma sempre acceso sul Mac (parte da solo al login). Accende e spegne Jarvis, apre MetaTrader 5, mostra la pagina per l'iPhone |
| **Pagina iPhone** | `telefono.html` (servita dal custode) | Da Safari, solo tramite Tailscale e con il PIN: Accendi/Spegni, grafico cervello → squadre, Mac e trader, squadre, attività automatiche, compiti, rapporto |
| **Telegram** | stesso bot | Jarvis spento: risponde il custode a `/accendi` e `/stato`. Jarvis acceso: `/stato` e `/spegni` (con il SÌ) |
| **Diario attività** | `attivita.py`, `dati/attivita.jsonl` | Cosa fa Jarvis da solo: approvazioni, aggiornamenti, AI di riserva, controlli, briefing, post, compiti, accensioni |
| **Compiti dal telefono** | `pannello.py` | Scegli la squadra e scrivi il compito: passa dal cervello, il risultato arriva su Telegram. Le azioni critiche chiedono sempre il SÌ |

Regole invariate: il custode non tocca STOP.txt, non apre né chiude operazioni, non cambia i parametri del trader; il conto resta demo.

## Cosa devi fare tu (una volta sola)

1. **PIN**: nel `.env` deve esserci `JARVIS_PIN=` con almeno 4 cifre (è lo stesso della Dispensa). Senza PIN la pagina da fuori resta chiusa.
2. **Installa il custode**: doppio clic su `installa_custode.command` nella cartella jarvis. Alla fine deve dire «Custode installato» e «Tailscale: la pagina è … porta 8443».
3. **Il Mac non deve andare in stop**: Impostazioni di Sistema → Batteria (o Risparmio energia) → Opzioni → attiva «Impedisci lo stop automatico quando lo schermo è spento» con l'alimentatore.
4. **Riavvia Jarvis** (`/riavvia` su Telegram): così prende le novità.
5. **Sull'iPhone**: Safari → `https://<nome-del-mac>.<tua-rete>.ts.net:8443` (lo stesso indirizzo della Dispensa con `:8443` in fondo) → PIN → Condividi → «Aggiungi alla schermata Home».

## Prove da fare

- Su Telegram `/stato` con Jarvis acceso → risponde Jarvis.
- `/spegni` → SÌ → Jarvis si spegne; dopo circa 20 secondi `/stato` → risponde il custode («Jarvis spento»).
- `/accendi` → «Accendo…» poi «✅ Jarvis acceso alle …, MetaTrader 5 aperto».
- Dalla pagina: Spegni (due tocchi) e Accendi (due tocchi).

## Se qualcosa non va

- Registro del custode: `~/jarvis/dati/custode.log`.
- Stato del custode: `launchctl print gui/$(id -u)/it.jarvis.custode | head`.
- Toglierlo: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/it.jarvis.custode.plist`.
- Accensione: il custode apre `avvia_jarvis.command` come il doppio clic. Se Jarvis non parte entro 2 minuti e mezzo ti avvisa: guarda il Terminale.
