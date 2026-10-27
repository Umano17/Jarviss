"""Guardiano di Jarvis (3.7): avvia server.py e lo tiene d'occhio.

- Se Jarvis esce con il codice 75 (aggiornamento o /riavvia) lo fa ripartire.
- Dopo un aggiornamento (dati/aggiornamento.json con stato «in_prova») controlla che Jarvis risponda su
  /api/salute entro 90 secondi. Se non risponde o si chiude, torna da solo alla versione precedente
  (git reset al commit di prima), lo fa ripartire e avvisa su Telegram.
- Ctrl + C nel Terminale ferma Jarvis e il guardiano.
Si avvia da avvia_jarvis.command (python avvio.py). I dati in dati/ e il .env non vengono mai toccati.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
FILE_STATO = BASE / "dati" / "aggiornamento.json"
CODICE_RIAVVIO = 75
SECONDI_PROVA = 90
URL_SALUTE = "http://127.0.0.1:8765/api/salute"


def _stato() -> dict:
    try:
        return json.loads(FILE_STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _scrivi(**campi) -> None:
    d = _stato()
    d.update(campi)
    FILE_STATO.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE_STATO.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE_STATO)


def _telegram(testo: str) -> None:
    """Avviso diretto, senza caricare Jarvis (legge solo token e chat da segreteria/config.py)."""
    print("Guardiano:", testo)
    try:
        import attivita
        attivita.registra(testo, "guardiano", "errore" if "🚨" in testo else "avviso" if "⚠️" in testo else "ok")
    except Exception:
        pass
    try:
        spec = importlib.util.spec_from_file_location("cfg_guardiano", BASE / "segreteria" / "config.py")
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        token, chat = getattr(cfg, "TELEGRAM_TOKEN", ""), getattr(cfg, "TELEGRAM_CHAT_ID", "")
        if not token or not chat or "incolla" in str(token):
            return
        dati = urllib.parse.urlencode({"chat_id": chat, "text": testo[:4000]}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dati, timeout=15)
    except Exception as e:
        print("Guardiano: Telegram non raggiungibile:", repr(e)[:150])


def _sano() -> bool:
    try:
        with urllib.request.urlopen(URL_SALUTE, timeout=5) as r:
            return json.loads(r.read().decode()).get("ok") is True
    except Exception:
        return False


def _torna_indietro(st: dict, motivo: str) -> None:
    da = st.get("da", "")
    r = subprocess.run(["git", "reset", "--hard", da], cwd=BASE, capture_output=True, text=True)
    if r.returncode == 0:
        _scrivi(stato="annullato", motivo=motivo, tornato_a=da)
        _telegram(f"⚠️ L'aggiornamento non funzionava ({motivo}): sono tornato da solo alla versione "
                  f"precedente ({da[:7]}) e riavvio Jarvis.")
    else:
        _scrivi(stato="errore", motivo=motivo + " · ritorno fallito: " + r.stderr[:200])
        _telegram(f"🚨 L'aggiornamento non funzionava e NON riesco a tornare indietro: {r.stderr[:200]}. "
                  "Serve un controllo sul Mac.")


FILE_PID = BASE / "dati" / "jarvis_pid.json"     # letto dal custode (custode.py) per spegnere Jarvis


def _segna_pid(acceso: bool) -> None:
    try:
        if acceso:
            FILE_PID.parent.mkdir(parents=True, exist_ok=True)
            FILE_PID.write_text(json.dumps({"pid": os.getpid(), "avviato": time.time()}), encoding="utf-8")
        elif FILE_PID.exists():
            FILE_PID.unlink()
    except OSError:
        pass


def _ferma(*_):
    raise KeyboardInterrupt        # SIGTERM dal custode (spegni a distanza) = come Ctrl + C


def main() -> None:
    signal.signal(signal.SIGTERM, _ferma)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    _segna_pid(True)
    try:
        _ciclo()
    finally:
        _segna_pid(False)


def _ciclo() -> None:
    env = dict(os.environ, JARVIS_GUARDIANO="1")
    cadute_di_fila = 0
    while True:
        st = _stato()
        in_prova = st.get("stato") == "in_prova"
        figlio = subprocess.Popen([sys.executable, "server.py"], cwd=BASE, env=env)
        try:
            if in_prova:
                fine = time.time() + SECONDI_PROVA
                while time.time() < fine and figlio.poll() is None and not _sano():
                    time.sleep(2)
                if figlio.poll() is None and _sano():
                    _scrivi(stato="ok", confermato=time.strftime("%Y-%m-%d %H:%M"))
                    _telegram(f"✅ Aggiornamento riuscito: Jarvis è ripartito ({st.get('a', '')[:7]}).")
                else:
                    if figlio.poll() is None:
                        figlio.terminate()
                        try:
                            figlio.wait(15)
                        except subprocess.TimeoutExpired:
                            figlio.kill()
                    _torna_indietro(st, "Jarvis non rispondeva dopo il riavvio")
                    continue
            codice = figlio.wait()
        except KeyboardInterrupt:          # Ctrl + C: si ferma tutto
            try:
                figlio.terminate()
                figlio.wait(15)
            except Exception:
                figlio.kill()
            print("\nGuardiano: Jarvis fermato.")
            return
        if codice == CODICE_RIAVVIO:
            print("Guardiano: riavvio Jarvis…")
            cadute_di_fila = 0
            continue
        if codice in (0, -signal.SIGINT, 130, -signal.SIGTERM):
            print("Guardiano: Jarvis chiuso.")
            return
        cadute_di_fila += 1
        _telegram(f"⚠️ Jarvis si è chiuso da solo (codice {codice}).")
        if cadute_di_fila >= 3:
            print("Guardiano: Jarvis si chiude di continuo, mi fermo. Controlla il Terminale.")
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
