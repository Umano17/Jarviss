"""Memoria di Jarvis (secondo cervello): note permanenti che Jarvis richiama da solo quando servono.

Categorie:
  istruzione  -> regole sempre valide ("scrivi sempre in prima persona"): entrano in OGNI risposta
  business    -> chi sei, cosa vendi, obiettivi
  listino     -> prezzi e condizioni (il listino vero e proprio è in Produttività)
  stile       -> come scrivi, parole da usare o evitare
  cliente     -> informazioni su un cliente
  altro
Le altre categorie entrano solo se pertinenti alla domanda (parole in comune), massimo 5 note.
Salvate in dati/memoria.json (restano solo sul Mac).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import unicodedata
from pathlib import Path

FILE = Path(__file__).parent / "dati" / "memoria.json"
CATEGORIE = ("istruzione", "business", "listino", "stile", "cliente", "altro")
_lock = threading.RLock()
_VUOTE = set("""il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi cui non piu più
del dello della dei degli delle al allo alla ai agli alle dal dalla dai nel nella nei sul sulla come anche
sono sei siamo è ho hai ha abbiamo questo questa quello quella mio mia tuo tua suo sua mi ti si ci vi
fare fai fa puoi può voglio vorrei dimmi cosa quale quali quanto quando dove the and for""".split())


def _ora():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _leggi() -> list[dict]:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _scrivi(lista: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)


def _parole(testo: str) -> set[str]:
    t = unicodedata.normalize("NFKD", (testo or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in _VUOTE}


def elenco(categoria: str = "") -> list[dict]:
    with _lock:
        l = _leggi()
    return [n for n in reversed(l) if not categoria or n["categoria"] == categoria]


def salva(titolo: str, testo: str, categoria: str = "altro") -> tuple[dict | None, str]:
    titolo, testo = (titolo or "").strip()[:120], (testo or "").strip()[:2000]
    if not testo:
        return None, "Scrivi il contenuto della nota."
    if categoria not in CATEGORIE:
        categoria = "altro"
    if not titolo:
        titolo = testo[:60] + ("…" if len(testo) > 60 else "")
    with _lock:
        l = _leggi()
        # stessa nota (stesso titolo e categoria): la aggiorno invece di duplicarla
        for n in l:
            if n["titolo"].lower() == titolo.lower() and n["categoria"] == categoria:
                n.update(testo=testo, aggiornata=_ora())
                _scrivi(l)
                return n, ""
        n = {"id": max((x["id"] for x in l), default=0) + 1, "titolo": titolo, "testo": testo,
             "categoria": categoria, "creata": _ora(), "aggiornata": _ora()}
        l.append(n)
        _scrivi(l)
        return n, ""


def modifica(id_: int, **campi) -> dict | None:
    with _lock:
        l = _leggi()
        for n in l:
            if n["id"] == int(id_):
                if campi.get("titolo"):
                    n["titolo"] = str(campi["titolo"])[:120]
                if campi.get("testo"):
                    n["testo"] = str(campi["testo"])[:2000]
                if campi.get("categoria") in CATEGORIE:
                    n["categoria"] = campi["categoria"]
                n["aggiornata"] = _ora()
                _scrivi(l)
                return n
    return None


def elimina(id_: int) -> bool:
    with _lock:
        l = _leggi()
        nuova = [n for n in l if n["id"] != int(id_)]
        if len(nuova) == len(l):
            return False
        _scrivi(nuova)
        return True


def cerca(domanda: str, limite: int = 5, escludi_istruzioni: bool = True) -> list[dict]:
    q = _parole(domanda)
    punteggi = []
    for n in _leggi():
        if escludi_istruzioni and n["categoria"] == "istruzione":
            continue
        p = len(q & _parole(n["titolo"])) * 3 + len(q & _parole(n["testo"]))
        if p > 0:
            punteggi.append((p, n["aggiornata"], n))
    punteggi.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [n for _, _, n in punteggi[:limite]]


def contesto(domanda: str = "", limite: int = 5) -> str:
    """Il testo da aggiungere al prompt: istruzioni sempre + note pertinenti. Vuoto se non c'è nulla."""
    with _lock:
        tutte = _leggi()
    istr = [n for n in tutte if n["categoria"] == "istruzione"]
    rilevanti = cerca(domanda, limite) if domanda else []
    if not istr and not rilevanti:
        return ""
    righe = [f"- [{n['categoria']}] {n['titolo']}: {n['testo']}" for n in istr + rilevanti]
    return ("MEMORIA DI " + os.getenv("NOME_UTENTE", "Jonatan").upper() +
            " (note salvate da lui: usale come contesto; le istruzioni valgono sempre)\n" + "\n".join(righe))


def testo_per_jarvis(note: list[dict]) -> str:
    if not note:
        return "Nessuna nota trovata in memoria."
    return "\n".join(f"#{n['id']} [{n['categoria']}] {n['titolo']}: {n['testo']}" for n in note)
