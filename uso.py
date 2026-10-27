"""Quanto lavora ogni reparto: richieste, token e ricerche web, registrati in uso.jsonl.

Il costo in euro compare solo se imposti i prezzi nel file .env (li trovi sul sito del tuo fornitore):
  PREZZO_INPUT_PER_MILIONE=...   PREZZO_OUTPUT_PER_MILIONE=...   PREZZO_PER_RICERCA=...   PREZZO_VALUTA=€
Senza prezzi vedi comunque i token, che sono il dato certo.
"""
import json
import os
import threading
import time
from pathlib import Path

FILE = Path(__file__).parent / "uso.jsonl"
_lock = threading.Lock()
REPARTI = ("jarvis", "agenda", "ricerca", "lead", "notizie", "siti", "segreteria", "produttivita")

# per sapere quanto costa ogni cliente: chi lavora per un cliente lo dichiara con  with uso.per_cliente(id): ...
_rif = threading.local()


class per_cliente:
    """Le chiamate al modello fatte dentro questo blocco vengono attribuite al cliente (cid) o alla demo (slug)."""
    def __init__(self, cliente=None, demo=None):
        self.c, self.d = cliente, demo

    def __enter__(self):
        self.prima = (getattr(_rif, "c", None), getattr(_rif, "d", None))
        _rif.c, _rif.d = (self.c if self.c is not None else self.prima[0]), (self.d or self.prima[1])
        return self

    def __exit__(self, *a):
        _rif.c, _rif.d = self.prima
        return False


def registra(reparto, risposta):
    """Annota l'uso di una risposta del modello. Non deve mai far fallire il lavoro."""
    try:
        u = getattr(risposta, "usage", None)
        if u is None:
            return
        web = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        riga = {"t": int(time.time()), "r": reparto if reparto in REPARTI else "jarvis",
                "i": int(getattr(u, "input_tokens", 0) or 0), "o": int(getattr(u, "output_tokens", 0) or 0),
                "w": int(web),
                # token letti dalla cache (costano ~1/10) e scritti in cache (~1,25 volte)
                "cr": int(getattr(u, "cache_read_input_tokens", 0) or 0),
                "cw": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}
        if getattr(risposta, "ai", None):          # risposta data da un'AI di riserva (ai.py)
            riga["a"] = risposta.ai
        if getattr(_rif, "c", None) is not None:
            riga["c"] = _rif.c
        if getattr(_rif, "d", None):
            riga["d"] = _rif.d
        with _lock:
            with open(FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(riga) + "\n")
    except Exception as e:
        print("Uso: non riesco a registrare:", e)


def _prezzo(nome, chiave):
    """Prima i prezzi scritti nella schermata (scheda Uso), poi quelli del file .env."""
    try:
        import impostazioni
        v = impostazioni.carica().get(chiave, "")
        if v != "":
            return float(v)
    except Exception:
        pass
    try:
        return float(os.getenv(nome, "").replace(",", "."))
    except ValueError:
        return None


def riepilogo(giorni=30):
    da = time.time() - giorni * 86400
    per = {r: {"reparto": r, "richieste": 0, "token_in": 0, "token_out": 0, "ricerche": 0} for r in REPARTI}
    per_ai = {}      # quale AI ha risposto (Claude o una riserva di ai.py)
    try:
        with _lock:
            righe = FILE.read_text(encoding="utf-8").splitlines()[-30000:]
    except OSError:
        righe = []
    for riga in righe:
        try:
            x = json.loads(riga)
        except ValueError:
            continue
        if x.get("t", 0) < da or x.get("r") not in per:
            continue
        p = per[x["r"]]
        a = per_ai.setdefault(x.get("a", "claude"), {"ai": x.get("a", "claude"), "richieste": 0, "token": 0})
        a["richieste"] += 1
        a["token"] += x.get("i", 0) + x.get("o", 0) + x.get("cr", 0) + x.get("cw", 0)
        p["richieste"] += 1
        p["token_in"] += x.get("i", 0) + x.get("cr", 0) + x.get("cw", 0)
        p["_in_pesati"] = p.get("_in_pesati", 0) + x.get("i", 0) + 0.1 * x.get("cr", 0) + 1.25 * x.get("cw", 0)
        p["token_out"] += x.get("o", 0)
        p["ricerche"] += x.get("w", 0)
    pi, po, pr = _prezzo("PREZZO_INPUT_PER_MILIONE", "prezzoIn"), _prezzo("PREZZO_OUTPUT_PER_MILIONE", "prezzoOut"), _prezzo("PREZZO_PER_RICERCA", "prezzoRic")
    prezzi = pi is not None and po is not None
    for p in per.values():
        p["costo"] = None
        if prezzi:
            p["costo"] = round(p.get("_in_pesati", p["token_in"]) / 1e6 * pi + p["token_out"] / 1e6 * po + p["ricerche"] * (pr or 0), 2)
    for p in per.values():
        p.pop("_in_pesati", None)
    lista = sorted(per.values(), key=lambda p: (p["token_in"] + p["token_out"]), reverse=True)
    tot = {k: sum(p[k] for p in lista) for k in ("richieste", "token_in", "token_out", "ricerche")}
    tot["costo"] = round(sum(p["costo"] for p in lista), 2) if prezzi else None
    return {"giorni": giorni, "reparti": lista, "totale": tot, "valuta": os.getenv("PREZZO_VALUTA", "€").strip() or "€",
            "prezzi_impostati": prezzi, "per_ai": sorted(per_ai.values(), key=lambda a: -a["richieste"]),
            "prezzi": {"in": pi, "out": po, "ric": pr}}


def costo_per(clienti_demo):
    """Costo del modello per cliente. clienti_demo = {id_cliente: slug_demo_o_None}.
    Restituisce {id: {"token": n, "ricerche": n, "costo": euro_o_None}}."""
    out = {cid: {"token": 0, "ricerche": 0, "_pesati": 0.0, "_out": 0} for cid in clienti_demo}
    per_demo = {s: cid for cid, s in clienti_demo.items() if s}
    try:
        with _lock:
            righe = FILE.read_text(encoding="utf-8").splitlines()[-50000:]
    except OSError:
        righe = []
    for riga in righe:
        try:
            x = json.loads(riga)
        except ValueError:
            continue
        cid = x.get("c") if x.get("c") in out else per_demo.get(x.get("d"))
        if cid is None:
            continue
        o = out[cid]
        o["token"] += x.get("i", 0) + x.get("o", 0) + x.get("cr", 0) + x.get("cw", 0)
        o["ricerche"] += x.get("w", 0)
        o["_pesati"] += x.get("i", 0) + 0.1 * x.get("cr", 0) + 1.25 * x.get("cw", 0)
        o["_out"] += x.get("o", 0)
    pi, po, pr = _prezzo("PREZZO_INPUT_PER_MILIONE", "prezzoIn"), _prezzo("PREZZO_OUTPUT_PER_MILIONE", "prezzoOut"), _prezzo("PREZZO_PER_RICERCA", "prezzoRic")
    for o in out.values():
        o["costo"] = (round(o["_pesati"] / 1e6 * pi + o["_out"] / 1e6 * po + o["ricerche"] * (pr or 0), 2)
                      if pi is not None and po is not None else None)
        o.pop("_pesati")
        o.pop("_out")
    return out
