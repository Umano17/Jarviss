"""Progetti di Jarvis: una cartella (sul Mac e su Google Drive) per ogni progetto, condivisa dagli agenti.

Ogni progetto ha un file progetto.md: è lo stato condiviso. Ogni agente lo legge prima di lavorare e vi
lascia una riga di registro quando finisce, così più agenti lavorano nella stessa cartella senza pestarsi i piedi.
Gli agenti aggiungono file (v1, v2, ...), non cancellano e non sovrascrivono.
"""
import datetime as dt
import json
import os
import re
import shutil
import threading
import unicodedata
from pathlib import Path

import rubrica

BASE = Path(__file__).parent
CARTELLA = BASE / "progetti"
FILE = BASE / "progetti.json"
_lock = threading.RLock()
NOME_UTENTE = os.getenv("NOME_UTENTE", "Jonatan").strip() or "Jonatan"

AGENTI = {"agenda": "Agenda", "ricerca": "Ricerca", "lead": "Lead", "notizie": "Notizie", "siti": "Siti web",
          "produttivita": "Produttività"}

TIPI = {
    "sito": {"nome": "Sito web", "agenti": ["siti", "ricerca"], "cartelle": [
        ("01 Ricerca", "scheda attività e dati pubblici"), ("02 Demo", "versioni v1, v2…"),
        ("03 SEO locale", "parole chiave e testi"), ("04 Messaggi", "bozze per il titolare"),
        ("05 Preventivo", "offerta e condizioni"), ("06 Consegna", "file finali e istruzioni"),
        ("Feedback", "commenti e correzioni")]},
    "ricerca": {"nome": "Ricerca", "agenti": ["ricerca", "notizie"], "cartelle": [
        ("01 Domanda", "obiettivo e criteri"), ("02 Fonti", "link e appunti verificati"),
        ("03 Rapporto", "bozze e versione finale"), ("04 Dati", "tabelle e allegati"),
        ("Feedback", "commenti e correzioni")]},
    "altro": {"nome": "Altro", "agenti": ["agenda"], "cartelle": [
        ("01 Materiali", "file di partenza"), ("02 Lavori", "bozze"), ("03 Consegna", "versione finale"),
        ("Feedback", "commenti e correzioni")]},
}


def _ora():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def slug(testo):
    t = unicodedata.normalize("NFKD", str(testo)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "progetto"


def _t(v, n):
    return " ".join(str(v or "").split())[:n]


def _leggi():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _scrivi(lista):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)


def _trova(lista, id_):
    return next((p for p in lista if p["id"] == id_), None)


def elenco():
    with _lock:
        return sorted(_leggi(), key=lambda p: p.get("aggiornato", ""), reverse=True)


def dettaglio(id_):
    with _lock:
        p = _trova(_leggi(), id_)
    if not p:
        return None
    p = dict(p)
    p["tipo_nome"] = TIPI[p["tipo"]]["nome"]
    p["cartelle"] = TIPI[p["tipo"]]["cartelle"]
    p["cliente_dati"] = rubrica.trova(p["cliente"]) if p.get("cliente") else None
    p["percorso"] = str(CARTELLA / p["slug"])
    return p


def _md(p):
    t = TIPI[p["tipo"]]
    cli = rubrica.trova(p["cliente"]) if p.get("cliente") else None
    righe = [f"# {p['nome']}", "",
             f"- Tipo: {t['nome']}",
             f"- Cliente: {cli['nome'] + (' (' + cli['attivita'] + ')' if cli.get('attivita') else '') if cli else 'nessuno'}",
             f"- Creato: {p['creato']}",
             f"- Agenti collegati: {', '.join(AGENTI[a] for a in p['agenti']) or 'nessuno'}", "",
             "## Come si lavora in questa cartella",
             "Ogni agente legge questo file prima di cominciare e, quando finisce, aggiunge una riga al Registro.",
             "Non si cancella nulla e non si sovrascrive: i file nuovi si aggiungono (v1, v2, v3…).",
             f"Email, telefonate e pubblicazioni partono solo dopo il sì di {NOME_UTENTE}.", "",
             "## Struttura"]
    righe += [f"- {n}: {d}" for n, d in t["cartelle"]]
    righe += ["", "## Registro (dal più recente)"]
    righe += [f"- {r['ts']} · {r['agente']} · {r['testo']}" for r in reversed(p.get("registro", [])[-60:])] or ["- (vuoto)"]
    righe += ["", "## Feedback (dal più recente)"]
    righe += [f"- {f['ts']} · {f['testo']}" for f in reversed(p.get("feedback", [])[-60:])] or ["- (nessuno)"]
    return "\n".join(righe) + "\n"


def _scrivi_locale(p):
    base = CARTELLA / p["slug"]
    for n, _ in TIPI[p["tipo"]]["cartelle"]:
        (base / n).mkdir(parents=True, exist_ok=True)
    (base / "progetto.md").write_text(_md(p), encoding="utf-8")


def drive_pronto():
    try:
        from segreteria import google_account
        return google_account.token_presente()
    except Exception:
        return False


def _drive_stato(id_, **kw):
    with _lock:
        lista = _leggi()
        p = _trova(lista, id_)
        if p:
            p.setdefault("drive", {}).update(kw)
            _scrivi(lista)


def _sync_drive(id_):
    """Crea la cartella su Drive (in sottofondo) e carica progetto.md."""
    try:
        from segreteria import google_account
        with _lock:
            p = _trova(_leggi(), id_)
        if not p:
            return
        _drive_stato(id_, stato="in_corso", messaggio="Creo la cartella su Drive…")
        r = google_account.crea_cartella_progetto(p["nome"], [n for n, _ in TIPI[p["tipo"]]["cartelle"]], _md(p))
        _drive_stato(id_, stato="ok", messaggio="", id=r["id"], link=r["link"], sub=r["sub"], md_id=r["md_id"])
        _condividi(id_)
    except Exception as e:
        print("Progetti: Drive non raggiungibile:", repr(e))
        _drive_stato(id_, stato="errore", messaggio="Drive non raggiungibile: la cartella sul Mac è comunque pronta.")


def ruolo_link():
    """Cosa può fare chi apre il link della cartella Drive (DRIVE_LINK_RUOLO nel .env): reader di base."""
    r = os.getenv("DRIVE_LINK_RUOLO", "reader").strip().lower()
    return r if r in ("reader", "commenter", "writer") else "reader"


def _condividi(id_):
    """Apre la cartella del progetto a chi ha il link (niente più richieste di accesso)."""
    with _lock:
        p = _trova(_leggi(), id_)
    d = (p or {}).get("drive") or {}
    if d.get("stato") != "ok" or not d.get("id") or d.get("condiviso") == ruolo_link():
        return
    try:
        from segreteria import google_account
        ruolo = google_account.condividi_con_link(d["id"], ruolo_link())
        _drive_stato(id_, condiviso=ruolo)
    except Exception as e:
        print("Progetti: condivisione con link non riuscita:", repr(e))


def condividi_esistenti():
    """All'avvio: apre con il link anche le cartelle dei progetti creati prima."""
    if not drive_pronto():
        return
    for p in _leggi():
        _condividi(p["id"])


def sincronizza(id_):
    """Riprova a creare la cartella su Drive."""
    if not drive_pronto():
        return False
    threading.Thread(target=_sync_drive, args=(id_,), daemon=True).start()
    return True


def _md_su_drive(id_):
    with _lock:
        p = _trova(_leggi(), id_)
    d = (p or {}).get("drive") or {}
    if d.get("stato") == "ok" and d.get("md_id"):
        try:
            from segreteria import google_account
            google_account.aggiorna_progetto_md(d["md_id"], _md(p))
        except Exception as e:
            print("Progetti: aggiornamento Drive non riuscito:", repr(e))


def _in_background(f, *a):
    threading.Thread(target=f, args=a, daemon=True).start()


def crea(nome, tipo="altro", cliente=None, agenti=None):
    """Restituisce (progetto, errore)."""
    nome = _t(nome, 80)
    if not nome:
        return None, "Dai un nome al progetto."
    if tipo not in TIPI:
        return None, "Tipo di progetto non valido."
    if cliente is not None and not rubrica.trova(cliente):
        cliente = None
    ag = [a for a in (agenti if agenti is not None else TIPI[tipo]["agenti"]) if a in AGENTI]
    with _lock:
        lista = _leggi()
        if any(p["nome"].lower() == nome.lower() for p in lista):
            return None, "Esiste già un progetto con questo nome."
        s, n = slug(nome), 2
        while any(p["slug"] == s for p in lista):
            s = f"{slug(nome)}-{n}"
            n += 1
        p = {"id": max((x["id"] for x in lista), default=0) + 1, "slug": s, "nome": nome, "tipo": tipo,
             "cliente": cliente, "agenti": list(dict.fromkeys(ag)), "feedback": [],
             "registro": [{"ts": _ora(), "agente": "Jarvis", "testo": "Progetto creato."}],
             "creato": _ora()[:10], "aggiornato": _ora(),
             "drive": {"stato": "in_attesa" if drive_pronto() else "non_collegato",
                       "messaggio": "" if drive_pronto() else "Drive non ancora collegato."}}
        lista.append(p)
        _scrivi(lista)
        _scrivi_locale(p)
    if drive_pronto():
        _in_background(_sync_drive, p["id"])
    return dettaglio(p["id"]), ""


def _aggiorna(id_, f):
    with _lock:
        lista = _leggi()
        p = _trova(lista, id_)
        if not p:
            return None
        f(p)
        p["aggiornato"] = _ora()
        _scrivi(lista)
        _scrivi_locale(p)
        return dict(p)


def registra(id_, agente, testo):
    """Una riga di registro lasciata da un agente (o da Jarvis)."""
    testo = _t(testo, 300)
    if not testo:
        return False
    nome = AGENTI.get(agente, _t(agente, 30) or "Jarvis")
    p = _aggiorna(id_, lambda p: (p["registro"].append({"ts": _ora(), "agente": nome, "testo": testo}),
                                  p.__setitem__("registro", p["registro"][-200:])))
    if p:
        _in_background(_md_su_drive, id_)
    return bool(p)


def aggiungi_feedback(id_, testo):
    testo = str(testo or "").strip()[:1000]
    if not testo:
        return False
    ts = _ora()
    p = _aggiorna(id_, lambda p: (p["feedback"].append({"ts": ts, "testo": testo}),
                                  p["registro"].append({"ts": ts, "agente": NOME_UTENTE, "testo": "Nuovo feedback."}),
                                  p.__setitem__("registro", p["registro"][-200:])))
    if not p:
        return False
    cart = CARTELLA / p["slug"] / "Feedback"
    cart.mkdir(parents=True, exist_ok=True)
    nome_file = f"{ts.replace(':', '-').replace(' ', '_')}.md"
    (cart / nome_file).write_text(f"# Feedback del {ts}\n\n{testo}\n", encoding="utf-8")

    def _su_drive():
        d = p.get("drive") or {}
        if d.get("stato") == "ok":
            try:
                from segreteria import google_account
                if d.get("sub", {}).get("Feedback"):
                    google_account.aggiungi_file_progetto(d["sub"]["Feedback"], nome_file, f"# Feedback del {ts}\n\n{testo}\n")
            except Exception as e:
                print("Progetti: feedback non caricato su Drive:", repr(e))
        _md_su_drive(id_)
    _in_background(_su_drive)
    return True


def collega_agente(id_, agente, on=True):
    if agente not in AGENTI:
        return None
    def f(p):
        if on and agente not in p["agenti"]:
            p["agenti"].append(agente)
        if not on and agente in p["agenti"]:
            p["agenti"].remove(agente)
        p["registro"].append({"ts": _ora(), "agente": "Jarvis",
                              "testo": f"{AGENTI[agente]} {'collegato' if on else 'scollegato'}."})
    p = _aggiorna(id_, f)
    if p:
        _in_background(_md_su_drive, id_)
    return dettaglio(id_) if p else None


def allega_demo(id_, slug_demo):
    """Copia i file di una demo del sito in 02 Demo/ del progetto (versione nuova, mai sovrascritta)."""
    import siti
    with _lock:
        p = _trova(_leggi(), id_)
    if not p or p["tipo"] != "sito":
        return False
    sorg = siti.CARTELLA / slug_demo
    if not sorg.is_dir():
        return False
    dest_base = CARTELLA / p["slug"] / "02 Demo"
    dest_base.mkdir(parents=True, exist_ok=True)
    n = 1
    while (dest_base / f"v{n}").exists():
        n += 1
    dest = dest_base / f"v{n}"
    dest.mkdir()
    copiati = []
    for nome in ("index.html", "scheda.md", "messaggio.txt"):
        if (sorg / nome).exists():
            shutil.copy2(sorg / nome, dest / nome)
            copiati.append(nome)
    registra(id_, "siti", f"Demo salvata in 02 Demo/v{n} ({', '.join(copiati)}).")

    def _su_drive():
        d = p.get("drive") or {}
        try:
            if d.get("stato") == "ok" and d.get("sub", {}).get("02 Demo"):
                from segreteria import google_account
                for nome in copiati:
                    mt = "text/html" if nome.endswith(".html") else "text/plain"
                    google_account.aggiungi_file_progetto(d["sub"]["02 Demo"], f"v{n}-{nome}", (dest / nome).read_text(encoding="utf-8"), mt)
        except Exception as e:
            print("Progetti: demo non caricata su Drive:", repr(e))
    _in_background(_su_drive)
    return True


def leggi_md(id_):
    with _lock:
        p = _trova(_leggi(), id_)
    return _md(p) if p else None


def testo_per_jarvis():
    lista = elenco()
    if not lista:
        return "Nessun progetto."
    return "\n".join(f"#{p['id']} {p['nome']} ({TIPI[p['tipo']]['nome']}), agenti: "
                     f"{', '.join(AGENTI[a] for a in p['agenti']) or 'nessuno'}, feedback: {len(p['feedback'])}" for p in lista)
