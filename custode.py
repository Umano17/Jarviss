"""Custode di Jarvis (3.8): sempre acceso sul Mac, accende e spegne Jarvis a distanza.

- Parte da solo al login del Mac (LaunchAgent installato da installa_custode.command) e si riavvia se si chiude.
- Pagina per l'iPhone su http://127.0.0.1:8766, raggiungibile da fuori SOLO tramite Tailscale
  (tailscale serve --bg --https=8443 http://127.0.0.1:8766) e con il PIN (JARVIS_PIN nel .env).
  Mostra stato del Mac, Jarvis acceso/spento, pulsanti Accendi/Spegni e, con Jarvis acceso, il pannello
  (flusso cervello → squadre, cronologia, rapporto, compiti) che chiede a Jarvis in locale.
- Telegram (stesso bot di Jarvis): quando Jarvis è SPENTO ascolta lui e risponde a /accendi e /stato.
  Quando Jarvis è acceso tace: risponde Jarvis (/stato, /spegni con il SÌ).
- Accendi: apre avvia_jarvis.command (come il doppio clic) e aspetta che Jarvis risponda.
Usa solo la libreria standard di Python (funziona anche senza il venv). Token e chat non finiscono mai nei log.
Prova: python3 custode.py --stato
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORTA = 8766
URL_JARVIS = "http://127.0.0.1:8765"
FILE_PID = BASE / "dati" / "jarvis_pid.json"
FILE_SEGRETO = BASE / "dati" / "custode_segreto.txt"
DURATA_COOKIE = 30 * 86400
ATTESA_AVVIO = 150


# ---------------------------------------------------------------- configurazione (senza librerie esterne)

def _env() -> dict:
    out = {}
    try:
        for riga in (BASE / ".env").read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if riga and not riga.startswith("#") and "=" in riga:
                k, v = riga.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _telegram_cfg() -> tuple[str, str]:
    """Token e chat: prima dal .env (senza librerie), poi da segreteria/config.py."""
    e = _env()
    token, chat = e.get("TELEGRAM_TOKEN", ""), e.get("TELEGRAM_CHAT_ID", "")
    if token and chat and "incolla" not in token:
        return token, chat
    try:
        spec = importlib.util.spec_from_file_location("cfg_custode", BASE / "segreteria" / "config.py")
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        token, chat = str(getattr(cfg, "TELEGRAM_TOKEN", "") or ""), str(getattr(cfg, "TELEGRAM_CHAT_ID", "") or "")
        if token and chat and "incolla" not in token:
            return token, chat
    except Exception:
        pass
    return "", ""


def _ora() -> str:
    return dt.datetime.now().strftime("%H:%M")


def _diario(testo: str, tipo: str = "info") -> None:
    try:
        sys.path.insert(0, str(BASE))
        import attivita
        attivita.registra(testo, "custode", tipo)
    except Exception:
        pass


# ---------------------------------------------------------------- stato di Jarvis e del Mac

def jarvis_acceso() -> dict | None:
    try:
        with urllib.request.urlopen(URL_JARVIS + "/api/salute", timeout=4) as r:
            d = json.loads(r.read().decode())
            return d if d.get("ok") else None
    except Exception:
        return None


def _batteria() -> str:
    try:
        r = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
        import re
        m = re.search(r"(\d+)%", r)
        corrente = "alimentatore" if "AC Power" in r else "batteria"
        return f"{m.group(1)}% ({corrente})" if m else corrente
    except Exception:
        return ""


def _acceso_da_mac() -> str:
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
        import re
        sec = int(re.search(r"sec = (\d+)", out).group(1))
        ore = int((time.time() - sec) / 3600)
        return f"{ore // 24} g {ore % 24} h" if ore >= 24 else f"{ore} h"
    except Exception:
        return ""


def stato() -> dict:
    j = jarvis_acceso()
    d = {"jarvis": bool(j), "versione": (j or {}).get("versione", ""), "ora": _ora(),
         "batteria": _batteria(),
         "mac_acceso_da": _acceso_da_mac()}
    try:
        p = json.loads(FILE_PID.read_text(encoding="utf-8"))
        if j:
            sec = int(time.time() - p.get("avviato", time.time()))
            d["acceso_da"] = f"{sec // 3600} h {sec % 3600 // 60} min" if sec >= 3600 else f"{sec // 60} min"
    except (OSError, ValueError):
        pass
    return d


def testo_stato() -> str:
    s = stato()
    righe = [("🟢 Jarvis acceso" + (f" ({s['versione']})" if s["versione"] else "")) if s["jarvis"] else "🔴 Jarvis spento",
             f"Mac acceso da {s['mac_acceso_da'] or '?'}" + (f" · {s['batteria']}" if s["batteria"] else ""),
             f"Ore {s['ora']}"]
    if not s["jarvis"]:
        righe.append("Per accenderlo: /accendi")
    return "\n".join(righe)


# ---------------------------------------------------------------- accendi / spegni

_azione = threading.Lock()


def accendi() -> str:
    if not _azione.acquire(blocking=False):
        return "Sto già eseguendo un comando, aspetta un attimo."
    try:
        if jarvis_acceso():
            return f"Jarvis è già acceso ({_ora()})."
        _telegram_lascia()                      # da qui il bot lo ascolta Jarvis
        subprocess.Popen(["open", str(BASE / "avvia_jarvis.command")])
        fine = time.time() + ATTESA_AVVIO
        while time.time() < fine and not jarvis_acceso():
            time.sleep(3)
        if not jarvis_acceso():
            _diario("Accensione a distanza: Jarvis non ha risposto entro 2 minuti e mezzo", "errore")
            return (f"⚠️ Ho lanciato Jarvis ma non risponde dopo {ATTESA_AVVIO // 60} minuti ({_ora()}). "
                    "Controlla il Terminale sul Mac.")
        _diario("Jarvis acceso a distanza", "ok")
        return f"✅ Jarvis acceso alle {_ora()}."
    finally:
        _azione.release()


def spegni() -> str:
    if not _azione.acquire(blocking=False):
        return "Sto già eseguendo un comando, aspetta un attimo."
    try:
        if not jarvis_acceso():
            return f"Jarvis è già spento ({_ora()})."
        try:
            pid = int(json.loads(FILE_PID.read_text(encoding="utf-8"))["pid"])
            os.kill(pid, signal.SIGTERM)         # il guardiano lo tratta come Ctrl + C
        except (OSError, ValueError, KeyError):
            return "Non trovo il guardiano di Jarvis: è stato avviato senza avvia_jarvis.command? Spegnilo dal Mac."
        fine = time.time() + 40
        while time.time() < fine and jarvis_acceso():
            time.sleep(2)
        if jarvis_acceso():
            return f"⚠️ Jarvis non si è spento entro 40 secondi ({_ora()})."
        _diario("Jarvis spento a distanza", "info")
        return f"✅ Jarvis spento alle {_ora()}."
    finally:
        _azione.release()


# ---------------------------------------------------------------- Telegram (solo quando Jarvis è spento)

_tg = {"offset": None, "attivo": False}


def _tg_api(metodo: str, dati: dict, timeout: int = 15) -> dict:
    token, _ = _telegram_cfg()
    if not token:
        return {}
    corpo = json.dumps(dati).encode()
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    if not _tg.get("curl"):
        req = urllib.request.Request(url, corpo, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:     # risposta di Telegram (es. 409: il bot lo sta ascoltando Jarvis)
            print("Custode: Telegram ha risposto", e.code)
            return {}
        except Exception as e:                  # mai stampare l'indirizzo: contiene il token
            motivo = str(getattr(e, "reason", e))
            print("Custode: Telegram via Python non riesce:", type(e).__name__, motivo[:80], "→ uso curl")
            _tg["curl"] = True                  # il Python di sistema spesso non ha i certificati: curl usa quelli del Mac
    # curl legge l'indirizzo da stdin (-K -), così il token non compare nell'elenco dei processi
    conf = f'url = "{url}"\nheader = "Content-Type: application/json"\n'
    try:
        r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), "-K", "-", "-d", corpo.decode()],
                           input=conf, capture_output=True, text=True, timeout=timeout + 5)
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception as e:
        print("Custode: Telegram non raggiungibile neanche con curl:", type(e).__name__)
        return {}


def _manda(testo: str) -> None:
    _, chat = _telegram_cfg()
    if chat:
        _tg_api("sendMessage", {"chat_id": chat, "text": testo[:4000]})


def _telegram_lascia() -> None:
    """Conferma a Telegram gli ultimi messaggi letti e smette di ascoltare (prima che parta Jarvis)."""
    _tg["attivo"] = False
    if _tg["offset"] is not None:
        _tg_api("getUpdates", {"offset": _tg["offset"], "timeout": 0})


def _gestisci(m: dict, chat: str) -> None:
    if str((m.get("chat") or {}).get("id")) != chat or str((m.get("from") or {}).get("id")) != chat:
        return                                   # risponde solo a Jonatan
    t = (m.get("text") or "").strip().lower().split("@")[0]
    if t == "/accendi":
        _manda("Accendo Jarvis, ci vuole fino a un paio di minuti…")
        _manda(accendi())
    elif t == "/stato":
        _manda(testo_stato())
    elif t == "/spegni":
        _manda("Jarvis è già spento. Per accenderlo: /accendi")
    else:
        _manda("Jarvis è spento, ti risponde il custode. Comandi: /accendi, /stato")


def ciclo_telegram() -> None:
    token, chat = _telegram_cfg()
    if not token:
        print("Custode: Telegram non configurato, uso solo la pagina.")
        return
    spento_di_fila = 0
    while True:
        if jarvis_acceso():
            spento_di_fila, _tg["attivo"] = 0, False
            time.sleep(10)
            continue
        spento_di_fila += 1
        if spento_di_fila < 2:                   # due controlli di fila: Jarvis potrebbe star ripartendo
            time.sleep(10)
            continue
        _tg["attivo"] = True
        d = _tg_api("getUpdates", {"timeout": 20, "offset": _tg["offset"]}, timeout=30)
        if not d.get("ok"):
            time.sleep(10)                       # es. Jarvis ha ripreso il bot (conflitto): riprovo dopo
            continue
        for u in d.get("result", []):
            _tg["offset"] = u["update_id"] + 1
            if u.get("callback_query"):
                cb = u["callback_query"]
                _tg_api("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "Jarvis è spento: /accendi"})
                continue
            if u.get("message"):
                try:
                    _gestisci(u["message"], chat)
                except Exception as e:
                    print("Custode, messaggio:", type(e).__name__, str(e)[:120])


# ---------------------------------------------------------------- pagina per l'iPhone (via Tailscale + PIN)

def _segreto() -> bytes:
    try:
        return FILE_SEGRETO.read_bytes()
    except OSError:
        FILE_SEGRETO.parent.mkdir(parents=True, exist_ok=True)
        s = secrets.token_hex(32).encode()
        FILE_SEGRETO.write_bytes(s)
        os.chmod(FILE_SEGRETO, 0o600)
        return s


def _firma(scade: int) -> str:
    return f"{scade}.{hmac.new(_segreto(), str(scade).encode(), hashlib.sha256).hexdigest()}"


def _cookie_valido(valore: str) -> bool:
    try:
        scade = int(valore.split(".", 1)[0])
    except ValueError:
        return False
    return scade > time.time() and hmac.compare_digest(_firma(scade), valore)


_errori_pin = {"n": 0, "fino": 0.0}


class Pagina(BaseHTTPRequestHandler):
    server_version = "Custode"

    def log_message(self, *a):                  # niente log delle richieste (contengono cookie e percorsi)
        pass

    # --- chi sta chiamando
    def _locale(self) -> bool:
        return (self.headers.get("Host", "") in (f"127.0.0.1:{PORTA}", f"localhost:{PORTA}")
                and not self.headers.get("X-Forwarded-For") and not self.headers.get("Tailscale-User-Login"))

    def _tailscale(self) -> bool:
        host = self.headers.get("Host", "").split(":")[0]
        return bool(self.headers.get("Tailscale-User-Login")) and host.endswith(".ts.net")

    def _autorizzato(self) -> bool:
        if self._locale():
            return True
        for parte in self.headers.get("Cookie", "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == "custode" and _cookie_valido(v):
                return True
        return False

    def _origine_ok(self) -> bool:
        o = self.headers.get("Origin")
        if o is None:
            return self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")
        host = self.headers.get("Host", "")
        return o in (f"https://{host}", f"http://{host}")

    def _manda(self, codice: int, corpo: bytes, tipo: str = "application/json", extra: dict | None = None):
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, d: dict, codice: int = 200, extra: dict | None = None):
        self._manda(codice, json.dumps(d, ensure_ascii=False).encode(), extra=extra)

    def _corpo(self) -> dict:
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 20000)
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError):
            return {}

    def _ammesso(self) -> bool:
        if self._locale() or self._tailscale():
            return True
        self._json({"errore": "Accesso consentito solo da questo Mac o tramite Tailscale."}, 403)
        return False

    # --- GET
    def do_GET(self):
        if not self._ammesso():
            return
        percorso = urllib.parse.urlparse(self.path).path
        if percorso in ("/", "/index.html"):
            try:
                self._manda(200, (BASE / "telefono.html").read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self._json({"errore": "Manca telefono.html"}, 500)
            return
        if percorso in ("/icona.png", "/apple-touch-icon.png"):
            try:
                self._manda(200, (BASE / "icone" / "apple-touch-icon.png").read_bytes(), "image/png")
            except OSError:
                self._json({}, 404)
            return
        if not self._autorizzato():
            self._json({"errore": "pin"}, 401)
            return
        if percorso == "/api/stato":
            self._json(stato())
        elif percorso == "/api/pannello":
            try:
                req = urllib.request.Request(URL_JARVIS + "/api/pannello")
                with urllib.request.urlopen(req, timeout=10) as r:
                    self._manda(200, r.read())
            except Exception:
                self._json({"errore": "Jarvis è spento o non risponde."}, 503)
        else:
            self._json({"errore": "non trovato"}, 404)

    # --- POST
    def do_POST(self):
        if not self._ammesso():
            return
        if not self._origine_ok():
            self._json({"errore": "origine non ammessa"}, 403)
            return
        percorso = urllib.parse.urlparse(self.path).path
        if percorso == "/accesso":
            pin = _env().get("JARVIS_PIN", "")
            if len(pin) < 4:
                self._json({"errore": "Accesso da fuori spento: imposta JARVIS_PIN (almeno 4 cifre) nel .env."}, 403)
                return
            if _errori_pin["fino"] > time.time():
                self._json({"errore": "Troppi tentativi: riprova tra qualche minuto."}, 429)
                return
            if hmac.compare_digest(str(self._corpo().get("pin", "")), pin):
                _errori_pin["n"] = 0
                scade = int(time.time()) + DURATA_COOKIE
                cookie = f"custode={_firma(scade)}; Max-Age={DURATA_COOKIE}; Path=/; HttpOnly; SameSite=Strict" + \
                         ("; Secure" if self._tailscale() else "")
                self._json({"ok": True}, extra={"Set-Cookie": cookie})
            else:
                _errori_pin["n"] += 1
                if _errori_pin["n"] >= 5:
                    _errori_pin.update(n=0, fino=time.time() + 900)
                    _diario("Pagina iPhone: 5 PIN sbagliati, accesso bloccato 15 minuti", "avviso")
                self._json({"errore": "PIN sbagliato."}, 401)
            return
        if not self._autorizzato():
            self._json({"errore": "pin"}, 401)
            return
        if percorso == "/api/accendi":
            self._json({"messaggio": accendi()})
        elif percorso == "/api/spegni":
            self._json({"messaggio": spegni()})
        elif percorso == "/api/compito":
            d = self._corpo()
            corpo = json.dumps({"squadra": str(d.get("squadra", ""))[:40], "testo": str(d.get("testo", ""))[:800]}).encode()
            req = urllib.request.Request(URL_JARVIS + "/api/pannello/compito", corpo,
                                         {"Content-Type": "application/json", "Origin": URL_JARVIS})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    self._manda(200, r.read())
            except Exception:
                self._json({"errore": "Jarvis è spento o non risponde."}, 503)
        else:
            self._json({"errore": "non trovato"}, 404)


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)      # il registro dati/custode.log si scrive subito
    except AttributeError:
        pass
    if "--stato" in sys.argv:
        print(testo_stato())
        return
    server = ThreadingHTTPServer(("127.0.0.1", PORTA), Pagina)     # solo locale: da fuori passa da Tailscale
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Custode attivo: pagina su http://127.0.0.1:{PORTA} (da fuori tramite Tailscale), Telegram quando Jarvis è spento.")
    ciclo_telegram()
    while True:                                  # senza Telegram resta acceso per la pagina
        time.sleep(3600)


if __name__ == "__main__":
    main()
