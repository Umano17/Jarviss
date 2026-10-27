"""Impostazioni della schermata di Jarvis (tema, orologio, briefing, voce...).

Salvate in impostazioni.json. Accetta solo valori previsti: niente di strano può finirci dentro.
"""
import json
import os
import threading
from pathlib import Path

FILE = Path(__file__).parent / "impostazioni.json"
_lock = threading.Lock()

SCELTE = {
    "tema": ("blu", "viola", "verde", "ghiaccio"),
    "pos": ("sx", "cx", "dx"),            # posizione dell'orologio
    "dim": ("s", "m", "l"),               # grandezza dell'orologio
    "vel": ("l", "n", "v"),               # velocità di volo nell'universo
    "brief": ("0", "1"),                  # mostra il briefing sullo schermo all'avvio
    "briefMac": ("0", "1"),               # notifica sul Mac all'accensione
    "briefVoce": ("0", "1"),              # lo legge a voce all'accensione
    "briefTg": ("0", "1"),                # lo invia anche su Telegram
    "riepSett": ("0", "1"),               # riepilogo settimanale su Telegram (lunedì)
    "testo": ("0", "1"),                  # mostra il testo delle risposte
    "usoUnita": ("t", "e"),               # scheda Uso: token (t) oppure euro (e)
}
NUMERICI = ("prezzoIn", "prezzoOut", "prezzoRic")   # prezzi per il costo in euro (scheda Uso)
PREDEFINITE = {"tema": "blu", "pos": "sx", "dim": "m", "vel": "n", "brief": "1", "briefMac": "1",
               "briefVoce": "0", "briefTg": "0", "riepSett": "0", "testo": "0", "voce": "", "usoUnita": "t",
               "prezzoIn": "", "prezzoOut": "", "prezzoRic": "", "potenza": 50, "fuso": ""}


def _fuso(v):
    """Fuso orario IANA (es. Europe/Rome) oppure "" = ora del Mac. Verificato con zoneinfo."""
    if v == "":
        return ""
    try:
        import orario
        return v if orario.valido(v) else None
    except Exception:
        return None


def _numero(v):
    """Un prezzo valido (da 0 a 100000), scritto come testo; altrimenti None."""
    try:
        n = float(str(v).replace(",", ".").strip())
    except ValueError:
        return None
    return str(n) if 0 <= n <= 100000 else None


def carica():
    with _lock:
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
    out = dict(PREDEFINITE)
    for k, v in (d if isinstance(d, dict) else {}).items():
        if k in SCELTE and str(v) in SCELTE[k]:
            out[k] = str(v)
        elif k == "voce" and isinstance(v, str):
            out[k] = v[:80]
        elif k in NUMERICI and _numero(v) is not None:
            out[k] = _numero(v)
        elif k == "potenza" and _potenza(v) is not None:
            out[k] = _potenza(v)
        elif k == "fuso" and isinstance(v, str) and _fuso(v) is not None:
            out[k] = v
    return out


def _potenza(v):
    """Manopola Potenza: intero da 1 a 100 (cambia la profondità del lavoro, non il modello)."""
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 100 else None


def salva(nuove):
    """Aggiorna solo le chiavi valide. Restituisce le impostazioni complete."""
    attuali = carica()
    for k, v in (nuove or {}).items():
        if k in SCELTE and str(v) in SCELTE[k]:
            attuali[k] = str(v)
        elif k == "voce" and isinstance(v, str):
            attuali[k] = v[:80]
        elif k in NUMERICI and (v == "" or _numero(v) is not None):
            attuali[k] = "" if v == "" else _numero(v)
        elif k == "potenza" and _potenza(v) is not None:
            attuali[k] = _potenza(v)
        elif k == "fuso" and isinstance(v, str) and _fuso(v) is not None:
            attuali[k] = v
    with _lock:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(attuali, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, FILE)
    return attuali
