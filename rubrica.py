"""Rubrica di Jarvis: contatti usati per email, telefonate e messaggi.

Salvata in rubrica.json. Un contatto segnato "non contattare" non riceve mai email da Jarvis.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

FILE = Path(__file__).parent / "rubrica.json"
_lock = threading.RLock()
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _t(v, n):
    return " ".join(str(v or "").split())[:n]


def _leggi():
    if FILE.exists():
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                return d
        except (OSError, ValueError):
            return []
        return []
    # primo avvio: porta con sé la vecchia rubrica scritta in segreteria/config.py, se c'era
    seme = []
    try:
        from segreteria import config
        for nome, mail in (getattr(config, "RUBRICA", {}) or {}).items():
            seme.append({"id": len(seme) + 1, "nome": _t(nome, 80).title(), "attivita": "", "telefono": "",
                         "email": _t(mail, 120).lower(), "note": "", "non_contattare": False,
                         "creato": time.strftime("%Y-%m-%d")})
    except Exception:
        pass
    if seme:
        _scrivi(seme)
    return seme


def _scrivi(lista):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)


def _pulisci(d, base=None):
    base = base or {}
    c = {
        "nome": _t(d.get("nome", base.get("nome")), 80),
        "attivita": _t(d.get("attivita", base.get("attivita")), 100),
        "telefono": _t(d.get("telefono", base.get("telefono")), 30),
        "email": _t(d.get("email", base.get("email")), 120).lower(),
        "note": str(d.get("note", base.get("note", "")) or "").strip()[:500],
        "non_contattare": bool(d.get("non_contattare", base.get("non_contattare", False))),
    }
    if not c["nome"]:
        return None, "Serve almeno il nome."
    if c["email"] and not EMAIL.match(c["email"]):
        return None, "L'indirizzo email non sembra valido."
    if c["telefono"] and not re.fullmatch(r"[+\d][\d\s().-]{4,29}", c["telefono"]):
        return None, "Il numero di telefono non sembra valido."
    return c, ""


def elenco(q=""):
    with _lock:
        lista = _leggi()
    q = (q or "").strip().lower()
    if q:
        lista = [c for c in lista if q in " ".join((c["nome"], c.get("attivita", ""), c.get("email", ""))).lower()]
    return sorted(lista, key=lambda c: c["nome"].lower())


def aggiungi(d):
    c, err = _pulisci(d)
    if err:
        return None, err
    with _lock:
        lista = _leggi()
        c["id"] = max((x["id"] for x in lista), default=0) + 1
        c["creato"] = time.strftime("%Y-%m-%d")
        lista.append(c)
        _scrivi(lista)
    return c, ""


def modifica(id_, d):
    with _lock:
        lista = _leggi()
        x = next((c for c in lista if c["id"] == id_), None)
        if not x:
            return None, "Contatto non trovato."
        c, err = _pulisci(d, x)
        if err:
            return None, err
        x.update(c)
        _scrivi(lista)
        return dict(x), ""


def elimina(id_):
    with _lock:
        lista = _leggi()
        resto = [c for c in lista if c["id"] != id_]
        if len(resto) == len(lista):
            return False
        _scrivi(resto)
        return True


def trova(id_):
    return next((c for c in elenco() if c["id"] == id_), None)


def trova_email(nome):
    """Indirizzo del contatto che corrisponde al nome detto a voce (solo se è uno solo)."""
    n = " ".join(str(nome or "").lower().split())
    if not n:
        return None
    lista = [c for c in elenco() if c.get("email")]
    esatti = [c for c in lista if c["nome"].lower() == n]
    if len(esatti) == 1:
        return esatti[0]["email"]
    parziali = [c for c in lista if n in c["nome"].lower() or n in c.get("attivita", "").lower()]
    return parziali[0]["email"] if len(parziali) == 1 else None


def bloccato(indirizzo):
    """True se questo indirizzo è di un contatto segnato 'non contattare'."""
    a = str(indirizzo or "").strip().lower()
    return any(c.get("non_contattare") and c.get("email") == a for c in elenco())
