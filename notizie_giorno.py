"""Notizie del giorno per il widget di Jarvis: titoli importanti con il link all'articolo.

Si aggiorna da solo ogni 6 ore (dalle 7 alle 23) mentre Jarvis è acceso; si spegne con
NOTIZIE_GIORNO_ATTIVE=no nel file .env. I link vengono tenuti solo se compaiono davvero
nei risultati della ricerca web, così non ci sono indirizzi inventati.
"""
import os
import re
import json
import time
import threading
from pathlib import Path

import cervello

FILE = Path(__file__).parent / "notizie_giorno.json"
INTERVALLO_ORE = 6   # era 3: ogni giro costa ~30.000 token di ricerche, 3 aggiornamenti al giorno bastano
CATEGORIE = ("Italia", "Mondo", "Economia", "Tecnologia")
_lock = threading.Lock()
_stato = {"agg": 0, "notizie": [], "in_corso": False, "errore": ""}

SYSTEM = """Sei l'agente notizie di Jarvis. Cerca sul web le notizie più importanti di oggi per un lettore italiano.
Fai più ricerche separate: Italia, mondo, economia e mercati, tecnologia. Scegli da 6 a 8 notizie davvero rilevanti
delle ultime 24 ore, da testate affidabili, senza doppioni sulla stessa vicenda.
Rispondi SOLO con un oggetto JSON in questa forma:
{"notizie":[{"categoria":"Italia","titolo":"titolo in italiano, max 110 caratteri","sintesi":"una frase in italiano, max 160 caratteri","fonte":"nome della testata","url":"link dell'articolo"}]}
La categoria è una tra: Italia, Mondo, Economia, Tecnologia.
Regole: l'url deve essere copiato esattamente da un risultato di ricerca che parla di quella notizia; mai link inventati,
ricostruiti o di pagine generiche. Non inventare fatti: se non sei sicuro di una notizia, lasciala fuori."""


def _norm(u):
    return str(u).split("#")[0].split("?utm")[0].rstrip("/").lower()


def _carica():
    if FILE.exists():
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
            _stato["agg"] = d.get("agg", 0)
            _stato["notizie"] = d.get("notizie", [])
        except Exception:
            pass


def _salva():
    FILE.write_text(json.dumps({"agg": _stato["agg"], "notizie": _stato["notizie"]}, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def _url_dai_risultati(contenuto):
    """Raccoglie gli indirizzi restituiti dalla ricerca web."""
    trovati = set()
    for b in contenuto:
        if getattr(b, "type", "") != "web_search_tool_result":
            continue
        risultati = getattr(b, "content", None)
        if not isinstance(risultati, list):
            continue
        for x in risultati:
            u = getattr(x, "url", None) or (x.get("url") if isinstance(x, dict) else None)
            if u:
                trovati.add(_norm(u))
    return trovati


def scarica():
    adesso = __import__("orario").adesso().strftime("%A %d %B %Y, %H:%M")
    messaggi = [{"role": "user", "content": f"Adesso è {adesso}. Trova le notizie più importanti di oggi."}]
    trovati, r = set(), None
    for _ in range(6):
        r = cervello.client.messages.create(
            model=cervello.MODEL,
            max_tokens=3000,
            system=SYSTEM,
            messages=messaggi,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        )
        cervello.uso.registra("notizie", r)
        trovati |= _url_dai_risultati(r.content)
        if r.stop_reason != "pause_turn":
            break
        messaggi = [messaggi[0], {"role": "assistant", "content": r.content}]
    testo = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", testo, re.S)
    dati = json.loads(m.group(0)) if m else {}
    notizie = []
    for n in dati.get("notizie", []):
        url = str(n.get("url", "")).strip()
        if not url.startswith(("https://", "http://")):
            continue
        if trovati and _norm(url) not in trovati:
            continue   # link non presente nei risultati di ricerca: scartato
        cat = str(n.get("categoria", "")).strip().capitalize()
        notizie.append({
            "categoria": cat if cat in CATEGORIE else "Mondo",
            "titolo": str(n.get("titolo", "")).strip()[:120],
            "sintesi": str(n.get("sintesi", "")).strip()[:180],
            "fonte": str(n.get("fonte", "")).strip()[:40],
            "url": url[:500],
        })
    return [n for n in notizie if n["titolo"]][:8]


def _lavora():
    try:
        notizie = scarica()
        with _lock:
            if notizie:
                _stato["notizie"] = notizie
                _stato["errore"] = ""
            else:
                _stato["errore"] = "Nessuna notizia verificata trovata: riprova più tardi."
            _stato["agg"] = time.time()
            _salva()
    except Exception as e:
        print("NOTIZIE DEL GIORNO:", e)
        with _lock:
            _stato["errore"] = "Aggiornamento non riuscito: riprova più tardi."
    finally:
        _stato["in_corso"] = False


def aggiorna(forza=False):
    """Avvia un aggiornamento in sottofondo (se non è già in corso e se serve)."""
    with _lock:
        if _stato["in_corso"]:
            return
        if not forza and time.time() - _stato["agg"] < INTERVALLO_ORE * 3600:
            return
        _stato["in_corso"] = True
    threading.Thread(target=_lavora, daemon=True).start()


def stato():
    with _lock:
        return {"agg": _stato["agg"], "notizie": list(_stato["notizie"]),
                "in_corso": _stato["in_corso"], "errore": _stato["errore"]}


def testo_per_jarvis():
    s = stato()
    if not s["notizie"]:
        return "Non ho ancora notizie del giorno: l'aggiornamento è " + ("in corso." if s["in_corso"] else "da fare.")
    return "\n".join(f"[{n['categoria']}] {n['titolo']} ({n['fonte']}): {n['sintesi']}" for n in s["notizie"])


def _ciclo():
    while True:
        if 7 <= __import__("orario").adesso().hour < 23:
            aggiorna()
        time.sleep(600)


def avvia():
    _carica()
    if os.getenv("NOTIZIE_GIORNO_ATTIVE", "si").strip().lower() in ("no", "0", "false"):
        print("Notizie del giorno: aggiornamento automatico spento (NOTIZIE_GIORNO_ATTIVE=no).")
        return
    threading.Thread(target=_ciclo, daemon=True).start()
