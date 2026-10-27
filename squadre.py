"""Jarvis 3.7 – Squadre degli agenti e squadra Support.

Ogni reparto ha una SQUADRA: un responsabile che riceve l'ordine e operatori con un compito ciascuno.
Le squadre sono descritte nella cartella squadre/ (un file .md per squadra, modificabile senza toccare il codice).

Il codice degli agenti dice chi sta lavorando con:
    with squadre.turno("siti", "ricercatore", "Cerco i dati di Bar Luna"):
        ...

La squadra SUPPORT controlla lo stress di ogni squadra (lavori in coda, attese lunghe, errori) e manda aiuto:
  - Rinforzi: permettono alla squadra di lavorare su più lavori insieme (oggi usati dai Siti web);
  - Riparatore: riprova un lavoro fallito per un problema passeggero (servizio sovraccarico, rete), con attese crescenti.

Prova dal Terminale:  python3 squadre.py
"""
from __future__ import annotations

import collections
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

BASE = Path(__file__).parent
CARTELLA = BASE / "squadre"

SOGLIA_AIUTO = 60          # stress oltre il quale arriva un rinforzo
SOGLIA_RILASCIO = 25       # stress sotto il quale il rinforzo torna in Support
ATTESA_LUNGA = 240         # secondi: un operatore occupato da più di così fa salire lo stress
FINESTRA_ERRORI = 15 * 60  # gli errori degli ultimi 15 minuti contano per lo stress

_lock = threading.RLock()
_squadre: dict[str, dict] = {}
_registro = collections.deque(maxlen=60)       # eventi di tutte le squadre (per la Sala controllo)
_avviato = False

# strumenti di Jarvis -> (squadra, operatore). Gli strumenti che lavorano "dentro" (lead, siti)
# segnano da soli i loro operatori.
STRUMENTI = {
    "agenda_leggi": ("agenda", "lettore"),
    "agenda_crea": ("agenda", "pianificatore"),
    "agenda_cancella": ("agenda", "pianificatore"),
    "ricerca": ("ricerca", "ricercatore"),
    "notizie_giorno": ("notizie", "redattore"),
    "sito_demo_crea": ("siti", "responsabile"),
    "siti_demo_elenco": ("siti", "responsabile"),
    "progetto_crea": ("progetti", "archivista-progetti"),
    "progetti_elenco": ("progetti", "archivista-progetti"),
    "progetto_stato": ("progetti", "archivista-progetti"),
    "progetto_annota": ("progetti", "archivista-progetti"),
    "rubrica_cerca": ("progetti", "rubrica"),
    "rubrica_aggiungi": ("progetti", "rubrica"),
    # reparto Produttività (3.5)
    "produttivita_stato": ("commerciale", "responsabile"),
    "clienti_elenco": ("commerciale", "archivista-clienti"),
    "lead_cerca": ("lead", "cercatore"),
    "cliente_aggiungi": ("commerciale", "archivista-clienti"),
    "cliente_aggiorna": ("commerciale", "archivista-clienti"),
    "messaggio_cliente": ("commerciale", "copywriter-commerciale"),
    "contenuto_crea": ("contenuti", "redattore"),
    "contenuti_ricorrenti": ("contenuti", "pianificatore"),
    "lavoro_crea": ("testi", "autore"),
    "lavoro_rivedi": ("testi", "revisore-testi"),
    "listino": ("amministrazione", "listino"),
    "listino_prezzo": ("amministrazione", "listino"),
    "preventivo_crea": ("amministrazione", "preventivi"),
    "preventivo_stato": ("amministrazione", "preventivi"),
    "incassi_riepilogo": ("amministrazione", "contabile-incassi"),
    "sito_pubblica": ("siti", "pubblicatore"),
    "sito_foto": ("siti", "fotografo"),
    "memoria_salva": ("progetti", "memoria"),
    "memoria_cerca": ("progetti", "memoria"),
}


# ---------------------------------------------------------------- lettura dei file squadre/*.md

def _leggi_file(f: Path) -> dict | None:
    testo = f.read_text(encoding="utf-8")
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", testo, re.S)
    if not m:
        return None
    meta = {}
    for riga in m.group(1).splitlines():
        k, _, v = riga.partition(":")
        if k.strip() and v.strip():
            meta[k.strip()] = v.strip().strip("\"'")
    operatori = {}
    for riga in m.group(2).splitlines():
        r = re.match(r"^\s*-\s*([a-z0-9\-]+)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$", riga)
        if r:
            operatori[r.group(1)] = {"id": r.group(1), "nome": r.group(2), "compito": r.group(3)}
    sid = meta.get("id") or f.stem
    return {"id": sid, "nome": meta.get("nome", sid), "colore": meta.get("colore", "#8f7bff"),
            "responsabile": meta.get("responsabile", "Responsabile"),
            "compito_responsabile": meta.get("compito_responsabile", "Riceve l'ordine, assegna i compiti, approva il risultato"),
            "ordine": int(meta.get("ordine", "50") or 50), "operatori": operatori}


def _nuovo_operatore(o: dict) -> dict:
    return {**o, "stato": "libero", "attivita": "", "dal": 0.0, "fatti": 0, "errori": 0, "aiuto_a": ""}


def carica() -> None:
    """Legge (o rilegge) le squadre dalla cartella squadre/, conservando i contatori già accumulati."""
    nuove = {}
    for f in sorted(CARTELLA.glob("*.md")):
        try:
            d = _leggi_file(f)
        except OSError as e:
            print("SQUADRE: file non letto", f.name, e)
            continue
        if d:
            nuove[d["id"]] = d
    with _lock:
        for sid, d in nuove.items():
            vecchia = _squadre.get(sid, {})
            ops = {"responsabile": _nuovo_operatore({"id": "responsabile", "nome": d["responsabile"],
                                                     "compito": d["compito_responsabile"]})}
            ops.update({k: _nuovo_operatore(o) for k, o in d["operatori"].items()})
            for k, o in ops.items():
                if k in vecchia.get("operatori", {}):
                    o.update({x: vecchia["operatori"][k][x] for x in ("stato", "attivita", "dal", "fatti", "errori", "aiuto_a")})
            _squadre[sid] = {
                **{k: d[k] for k in ("id", "nome", "colore", "ordine")},
                "operatori": ops,
                "coda": vecchia.get("coda", 0),
                "errori_t": vecchia.get("errori_t", collections.deque(maxlen=50)),
                "durate": vecchia.get("durate", collections.deque(maxlen=30)),
                "rinforzi": vecchia.get("rinforzi", []),
                "stress": vecchia.get("stress", 0),
            }


def _sq(squadra: str) -> dict | None:
    if not _squadre:
        carica()
    return _squadre.get(squadra)


def _evento(squadra: str, chi: str, testo: str, tipo: str = "info") -> None:
    _registro.appendleft({"t": time.time(), "squadra": squadra, "chi": chi, "testo": testo[:160], "tipo": tipo})


# ---------------------------------------------------------------- chi lavora adesso

@contextmanager
def turno(squadra: str, operatore: str, attivita: str = ""):
    """Segna un operatore come al lavoro per la durata del blocco; registra tempo ed eventuale errore.
    Se la squadra o l'operatore non esistono, il lavoro procede lo stesso (nessun blocco per Jarvis)."""
    with _lock:
        sq = _sq(squadra)
        op = sq["operatori"].get(operatore) if sq else None
        if op:
            op.update(stato="occupato", attivita=attivita[:120], dal=time.time())
            _evento(squadra, op["nome"], attivita or "al lavoro")
    inizio = time.time()
    try:
        yield
    except Exception as e:
        with _lock:
            if op:
                op.update(stato="errore", attivita=f"Errore: {str(e)[:100]}", dal=time.time())
                op["errori"] += 1
                sq["errori_t"].append(time.time())
                _evento(squadra, op["nome"], f"Errore: {str(e)[:120]}", "errore")
        raise
    else:
        with _lock:
            if op:
                op.update(stato="libero", attivita="", dal=0.0)
                op["fatti"] += 1
                sq["durate"].append(time.time() - inizio)


def per_strumento(nome: str):
    """Il turno giusto per uno strumento di Jarvis (o un blocco che non fa nulla)."""
    s = STRUMENTI.get(nome)
    if not s:
        return _nulla()
    return turno(s[0], s[1], nome.replace("_", " "))


@contextmanager
def _nulla():
    yield


def segna_coda(squadra: str, n: int) -> None:
    with _lock:
        sq = _sq(squadra)
        if sq:
            sq["coda"] = max(0, int(n))


def nota(squadra: str, testo: str, chi: str = "responsabile") -> None:
    """Annota nel registro (es. il responsabile che assegna o approva)."""
    with _lock:
        sq = _sq(squadra)
        nome = sq["operatori"].get(chi, {}).get("nome", chi) if sq else chi
        _evento(squadra, nome, testo)


# ---------------------------------------------------------------- stress e squadra Support

def _calcola_stress(sq: dict) -> int:
    ora = time.time()
    errori = sum(1 for t in sq["errori_t"] if ora - t < FINESTRA_ERRORI)
    lunghi = sum(1 for o in sq["operatori"].values() if o["stato"] == "occupato" and ora - o["dal"] > ATTESA_LUNGA)
    occupati = sum(1 for o in sq["operatori"].values() if o["stato"] == "occupato" and o["id"] != "responsabile")
    totale = max(1, len(sq["operatori"]) - 1)
    s = sq["coda"] * 25 + errori * 15 + lunghi * 25 + int(occupati / totale * 30)
    return max(0, min(100, s))


def rinforzi(squadra: str) -> int:
    """Quanti rinforzi della Support stanno aiutando questa squadra."""
    with _lock:
        sq = _sq(squadra)
        return len(sq["rinforzi"]) if sq else 0


def _giro_support() -> None:
    with _lock:
        sup = _squadre.get("support")
        ora = time.time()
        for sid, sq in _squadre.items():
            for o in sq["operatori"].values():          # un errore resta visibile 2 minuti, poi l'operatore torna libero
                if o["stato"] == "errore" and ora - o["dal"] > 120:
                    o.update(stato="libero", attivita="", dal=0.0)
            if sid == "support":
                continue
            sq["stress"] = _calcola_stress(sq)
        if not sup:
            return
        ops = sup["operatori"]
        liberi = [o for o in ops.values() if o["id"].startswith("rinforzo") and not o["aiuto_a"]]
        # 1) manda rinforzi alle squadre più sotto pressione
        for sq in sorted((s for k, s in _squadre.items() if k != "support"), key=lambda s: -s["stress"]):
            if sq["stress"] >= SOGLIA_AIUTO and liberi and len(sq["rinforzi"]) < 2:
                r = liberi.pop(0)
                r.update(aiuto_a=sq["id"], stato="occupato", attivita=f"Aiuta la squadra {sq['nome']}", dal=time.time())
                sq["rinforzi"].append(r["id"])
                _evento("support", r["nome"], f"Va in aiuto a {sq['nome']} (stress {sq['stress']}%)", "aiuto")
        # 2) rilascia i rinforzi quando la squadra si è calmata
        for sq in _squadre.values():
            if sq["id"] == "support" or not sq["rinforzi"] or sq["stress"] > SOGLIA_RILASCIO or sq["coda"]:
                continue
            rid = sq["rinforzi"].pop()
            r = ops.get(rid)
            if r:
                r.update(aiuto_a="", stato="libero", attivita="", dal=0.0)
                r["fatti"] += 1
                _evento("support", r["nome"], f"Rientra: {sq['nome']} è tornata tranquilla")
        con = ops.get("controllore")
        if con:
            in_aiuto = [o for o in ops.values() if o["aiuto_a"]]
            con.update(stato="occupato" if in_aiuto else "libero",
                       attivita=f"Coordina {len(in_aiuto)} interventi" if in_aiuto else "Sorveglia le squadre")
        sup["stress"] = int(100 * sum(1 for o in ops.values() if o["aiuto_a"]) /
                            max(1, sum(1 for o in ops.values() if o["id"].startswith("rinforzo"))))


def _ciclo() -> None:
    while True:
        try:
            _giro_support()
        except Exception as e:
            print("SQUADRE:", e)
        time.sleep(4)


def avvia() -> None:
    global _avviato
    with _lock:
        if _avviato:
            return
        _avviato = True
        carica()
    threading.Thread(target=_ciclo, daemon=True).start()


def _passeggero(e: Exception) -> bool:
    nome = type(e).__name__.lower()
    testo = str(e).lower()
    return any(x in nome for x in ("ratelimit", "timeout", "connection", "overloaded", "internalserver", "apistatus")) or \
        any(x in testo for x in ("overloaded", "rate limit", "529", "503", "502", "timed out", "temporarily"))


def riprova(squadra: str, funzione, *args, tentativi: int = 3, **kw):
    """Il Riparatore della Support: se il lavoro fallisce per un problema passeggero, riprova con attese crescenti."""
    attese = [8, 25, 60]
    for n in range(tentativi):
        try:
            return funzione(*args, **kw)
        except Exception as e:
            if n == tentativi - 1 or not _passeggero(e):
                raise
            attesa = attese[min(n, len(attese) - 1)]
            with _lock:
                sup = _squadre.get("support")
                rip = sup["operatori"].get("riparatore") if sup else None
                sq = _sq(squadra)
                nome_sq = sq["nome"] if sq else squadra
                if rip:
                    rip.update(stato="occupato", aiuto_a=squadra, attivita=f"Riprova per {nome_sq} tra {attesa}s", dal=time.time())
                    rip["fatti"] += 1
                _evento("support", rip["nome"] if rip else "Riparatore",
                        f"{nome_sq}: problema passeggero ({str(e)[:60]}), riprovo tra {attesa}s", "aiuto")
            time.sleep(attesa)
            with _lock:
                if rip:
                    rip.update(stato="libero", aiuto_a="", attivita="", dal=0.0)


# ---------------------------------------------------------------- per la Sala controllo

def stato() -> dict:
    with _lock:
        if not _squadre:
            carica()
        ora = time.time()
        squadre = []
        for sq in sorted(_squadre.values(), key=lambda s: (s["id"] == "support", s["ordine"], s["nome"])):
            ops = []
            for o in sq["operatori"].values():
                ops.append({k: o[k] for k in ("id", "nome", "compito", "stato", "attivita", "fatti", "errori", "aiuto_a")}
                           | {"da_sec": int(ora - o["dal"]) if o["dal"] else 0})
            durate = list(sq["durate"])
            squadre.append({
                "id": sq["id"], "nome": sq["nome"], "colore": sq["colore"], "stress": sq["stress"], "coda": sq["coda"],
                "rinforzi": [sq_op for sq_op in sq["rinforzi"]],
                "errori_recenti": sum(1 for t in sq["errori_t"] if ora - t < FINESTRA_ERRORI),
                "tempo_medio": round(sum(durate) / len(durate), 1) if durate else 0,
                "operatori": ops,
            })
        return {"squadre": squadre, "registro": list(_registro)[:40], "adesso": ora,
                "soglie": {"aiuto": SOGLIA_AIUTO, "rilascio": SOGLIA_RILASCIO}}


if __name__ == "__main__":
    carica()
    for s in stato()["squadre"]:
        print(f"{s['nome']}: " + ", ".join(o["nome"] for o in s["operatori"]))
