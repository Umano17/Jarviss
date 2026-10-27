"""Jarvis 3.7 – Reparto PRODUTTIVITÀ: i servizi che portano soldi.

Agenti (ognuno con la sua squadra in squadre/<id>.md):
  - Commerciale     clienti in pipeline (trovato → demo → contattato → risposta → trattativa → cliente / perso),
                    richiami a 3 e 7 giorni, messaggi preparati (mai inviati da solo)
  - Contenuti       post, newsletter, articoli SEO, thread, script video; anche ricorrenti ogni mese (solo bozze)
  - Testi           lavori su richiesta: brief → bozza → revisione → consegnato (ghostwriting, riscrittura, …)
  - Amministrazione listino, preventivi (con link di pagamento), abbonamenti mensili, incassi
  - Margine         incassato per cliente contro costo reale dell'AI per quel cliente (nessun credito finto)
Gli agenti Siti web, SEO locale, Blueprint e la pubblicazione demo stanno nei loro moduli e scrivono qui
i clienti e i preventivi.

Regole: nessun messaggio, email o pubblicazione parte da solo; i prezzi "da decidere" bloccano l'invio del
preventivo; nessun dato inventato ([da confermare] dove manca). Dati in dati/*.json (solo sul Mac).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import memoria
import uso

BASE = Path(__file__).parent
DATI = BASE / "dati"
_lock = threading.RLock()

STATI_CLIENTE = [
    ("trovato", "Trovato"), ("demo", "Demo pronta"), ("contattato", "Contattato"), ("risposta", "Ha risposto"),
    ("trattativa", "Trattativa"), ("cliente", "Cliente"), ("perso", "Perso"),
]
CHIAVI_STATO = [s for s, _ in STATI_CLIENTE]
TIPI_CONTENUTO = ["Post social", "Post LinkedIn", "Newsletter", "Articolo SEO", "Thread X", "Script video", "Descrizione Google Business"]
SERVIZI_TESTI = ["Ghostwriting", "Riscrittura", "Traduzione", "Testi per sito", "Proposta di consulenza", "Script di vendita"]
STATI_LAVORO = ["bozza", "revisione", "consegnato"]
STATI_PREVENTIVO = ["bozza", "inviato", "accettato", "pagato", "rifiutato"]

# Listino iniziale: i prezzi dei siti vengono dalla skill preventivo-sito; gli altri sono da decidere (None).
LISTINO_BASE = [
    {"id": "sito-3", "gruppo": "Siti web", "nome": "Sito ★★★ one-page", "prezzo": 390, "unita": "una tantum"},
    {"id": "sito-4", "gruppo": "Siti web", "nome": "Sito ★★★★ fino a 5 sezioni", "prezzo": 690, "unita": "una tantum"},
    {"id": "sito-6", "gruppo": "Siti web", "nome": "Sito ★★★★★★ su misura", "prezzo": 1190, "unita": "una tantum"},
    {"id": "gest-base", "gruppo": "Gestione mensile", "nome": "Gestione Base", "prezzo": 19, "unita": "mese"},
    {"id": "gest-plus", "gruppo": "Gestione mensile", "nome": "Gestione Plus", "prezzo": 39, "unita": "mese"},
    {"id": "gest-crescita", "gruppo": "Gestione mensile", "nome": "Gestione Crescita", "prezzo": 79, "unita": "mese"},
    {"id": "seo-audit", "gruppo": "SEO locale", "nome": "Controllo SEO locale e scheda Google", "prezzo": None, "unita": "una tantum"},
    {"id": "seo-sistemazione", "gruppo": "SEO locale", "nome": "Sistemazione scheda Google e dati", "prezzo": None, "unita": "una tantum"},
    {"id": "cont-post", "gruppo": "Contenuti", "nome": "Post social (singolo)", "prezzo": None, "unita": "pezzo"},
    {"id": "cont-pacchetto", "gruppo": "Contenuti", "nome": "Pacchetto contenuti mensile", "prezzo": None, "unita": "mese"},
    {"id": "cont-newsletter", "gruppo": "Contenuti", "nome": "Newsletter", "prezzo": None, "unita": "pezzo"},
    {"id": "cont-articolo", "gruppo": "Contenuti", "nome": "Articolo SEO", "prezzo": None, "unita": "pezzo"},
    {"id": "testi-ghost", "gruppo": "Testi su richiesta", "nome": "Ghostwriting", "prezzo": None, "unita": "pezzo"},
    {"id": "testi-riscrittura", "gruppo": "Testi su richiesta", "nome": "Riscrittura", "prezzo": None, "unita": "pezzo"},
    {"id": "testi-traduzione", "gruppo": "Testi su richiesta", "nome": "Traduzione", "prezzo": None, "unita": "pezzo"},
    {"id": "testi-sito", "gruppo": "Testi su richiesta", "nome": "Testi per sito", "prezzo": None, "unita": "pezzo"},
    {"id": "testi-vendita", "gruppo": "Testi su richiesta", "nome": "Script di vendita", "prezzo": None, "unita": "pezzo"},
    {"id": "scheda-prodotto", "gruppo": "Blueprint", "nome": "Scheda prodotto per e-commerce", "prezzo": None, "unita": "pezzo"},
]


# ---------------------------------------------------------------- archivio semplice (JSON atomico)

def _f(nome: str) -> Path:
    return DATI / f"{nome}.json"


def _leggi(nome: str, vuoto=None):
    try:
        return json.loads(_f(nome).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [] if vuoto is None else vuoto


def _scrivi(nome: str, dati) -> None:
    DATI.mkdir(parents=True, exist_ok=True)
    tmp = _f(nome).with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _f(nome))


def _ora() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _oggi() -> dt.date:
    return dt.date.today()


def _t(v, n=300) -> str:
    return str(v or "").strip()[:n]


def _nuovo_id(lista) -> int:
    return max((x["id"] for x in lista), default=0) + 1


def _euro(v) -> str:
    if v is None:
        return "[da decidere]"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (s[:-3] if s.endswith(",00") else s) + " €"


# ---------------------------------------------------------------- lavori in sottofondo (per la schermata)

_jobs: dict[str, dict] = {}


def avvia_job(descrizione: str, funzione, *args, **kw) -> str:
    """Esegue funzione in sottofondo; la schermata chiede lo stato con stato_job(id)."""
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "descrizione": descrizione, "stato": "in_corso", "inizio": time.time(), "risultato": None}

    def corri():
        try:
            _jobs[jid].update(stato="fatto", risultato=funzione(*args, **kw))
        except Exception as e:
            _jobs[jid].update(stato="errore", risultato={"errore": str(e)[:300]})
    threading.Thread(target=corri, daemon=True).start()
    for k in [k for k, j in _jobs.items() if time.time() - j["inizio"] > 3600]:
        _jobs.pop(k, None)
    return jid


def stato_job(jid: str) -> dict:
    return _jobs.get(jid) or {"stato": "sconosciuto"}


def jobs_in_corso() -> list[dict]:
    return [{"id": j["id"], "descrizione": j["descrizione"]} for j in _jobs.values() if j["stato"] == "in_corso"]


# ---------------------------------------------------------------- modello (passa sempre da cervello.crea)

def _modello(system: str, testo: str, max_tokens: int = 2500, cliente=None, ricerca: bool = False) -> str:
    import cervello
    with uso.per_cliente(cliente):
        if ricerca:
            return cervello.sotto_agente(system, testo, reparto="produttivita")
        r = cervello.crea("produttivita", model=cervello.MODEL, max_tokens=max_tokens,
                          system=cervello.sistema_in_cache(system),
                          messages=[{"role": "user", "content": testo}])
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


def _regole_scrittura() -> str:
    nome = os.getenv("NOME_UTENTE", "Jonatan")
    return (f"Scrivi in italiano per {nome}, che lavora come freelance (siti web e contenuti per attività locali). "
            "Mai inventare fatti, numeri, recensioni, premi, prezzi o dati del cliente: dove manca un dato scrivi "
            "[da confermare]. Niente frasi fatte o superlativi vuoti. Testo pronto da usare, senza commenti tuoi prima o dopo.")


# ================================================================= COMMERCIALE: clienti e pipeline

def clienti() -> list[dict]:
    with _lock:
        return _leggi("clienti")


def cliente(id_) -> dict | None:
    try:
        id_ = int(id_)
    except (TypeError, ValueError):
        return None
    return next((c for c in clienti() if c["id"] == id_), None)


def trova_cliente(testo: str) -> dict | None:
    """Per nome (anche parziale) o numero."""
    testo = _t(testo, 120).lower()
    if testo.isdigit():
        return cliente(int(testo))
    l = clienti()
    esatto = [c for c in l if c["nome"].lower() == testo]
    if esatto:
        return esatto[0]
    simili = [c for c in l if testo and testo in c["nome"].lower()]
    return simili[0] if len(simili) == 1 else None


def aggiungi_cliente(nome, citta="", categoria="", telefono="", email="", note="", stato="trovato",
                     demo_slug="", progetto_id=None, valore=None) -> tuple[dict | None, str]:
    nome = _t(nome, 100)
    if not nome:
        return None, "Serve il nome dell'attività o del cliente."
    if stato not in CHIAVI_STATO:
        stato = "trovato"
    with _lock:
        l = _leggi("clienti")
        if any(c["nome"].lower() == nome.lower() and c.get("citta", "").lower() == _t(citta, 80).lower() for c in l):
            return None, f"{nome} è già tra i clienti."
        c = {"id": _nuovo_id(l), "nome": nome, "citta": _t(citta, 80), "categoria": _t(categoria, 80),
             "telefono": _t(telefono, 40), "email": _t(email, 120), "note": _t(note, 1000), "stato": stato,
             "demo_slug": _t(demo_slug, 80), "progetto_id": progetto_id, "valore": valore,
             "link_demo": "", "richiamo": "", "richiami_fatti": 0,
             "storia": [{"ts": _ora(), "testo": f"Aggiunto ({dict(STATI_CLIENTE)[stato]})."}],
             "creato": _ora(), "aggiornato": _ora()}
        l.append(c)
        _scrivi("clienti", l)
    return c, ""


def aggiorna_cliente(id_, **campi) -> tuple[dict | None, str]:
    with _lock:
        l = _leggi("clienti")
        c = next((x for x in l if x["id"] == int(id_)), None)
        if not c:
            return None, "Cliente non trovato."
        nuovo = campi.get("stato")
        if nuovo and nuovo != c["stato"]:
            if nuovo not in CHIAVI_STATO:
                return None, "Stato non valido."
            c["storia"].append({"ts": _ora(), "testo": f"{dict(STATI_CLIENTE)[c['stato']]} → {dict(STATI_CLIENTE)[nuovo]}"})
            c["stato"] = nuovo
            # richiami automatici: dopo il primo contatto a 3 giorni; con una risposta o a fine percorso si tolgono
            if nuovo == "contattato" and not campi.get("richiamo"):
                c["richiamo"], c["richiami_fatti"] = (_oggi() + dt.timedelta(days=3)).isoformat(), 0
            elif nuovo in ("risposta", "cliente", "perso"):
                c["richiamo"] = ""
        for k in ("nome", "citta", "categoria", "telefono", "email", "demo_slug", "link_demo"):
            if k in campi and campi[k] is not None:
                c[k] = _t(campi[k], 200)
        if campi.get("note"):
            c["note"] = _t(campi["note"], 1000)
        if campi.get("nota"):
            c["storia"].append({"ts": _ora(), "testo": _t(campi["nota"], 300)})
        if "richiamo" in campi and campi["richiamo"] is not None:
            r = str(campi["richiamo"]).strip()
            if r and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r):
                return None, "Data del richiamo non valida (AAAA-MM-GG)."
            c["richiamo"] = r
        if "valore" in campi:
            try:
                c["valore"] = float(campi["valore"]) if campi["valore"] not in (None, "") else None
            except (TypeError, ValueError):
                pass
        if campi.get("progetto_id") is not None:
            c["progetto_id"] = campi["progetto_id"]
        c["storia"] = c["storia"][-60:]
        c["aggiornato"] = _ora()
        _scrivi("clienti", l)
        return c, ""


def richiamo_fatto(id_, esito: str = "") -> tuple[dict | None, str]:
    """Hai richiamato e non ha ancora deciso: il prossimo richiamo va a 7 giorni (poi Jarvis suggerisce di chiudere)."""
    c = cliente(id_)
    if not c:
        return None, "Cliente non trovato."
    n = c.get("richiami_fatti", 0) + 1
    prossimo = (_oggi() + dt.timedelta(days=7)).isoformat() if n < 2 else ""
    with _lock:
        l = _leggi("clienti")
        x = next(x for x in l if x["id"] == c["id"])
        x["richiami_fatti"], x["richiamo"], x["aggiornato"] = n, prossimo, _ora()
        x["storia"].append({"ts": _ora(), "testo": f"Richiamo n.{n} fatto" + (f": {_t(esito, 200)}" if esito else "") +
                            ("" if prossimo else " · nessun altro richiamo: valuta se segnarlo come perso")})
        _scrivi("clienti", l)
        return x, ""


def elimina_cliente(id_) -> bool:
    with _lock:
        l = _leggi("clienti")
        n = [c for c in l if c["id"] != int(id_)]
        if len(n) == len(l):
            return False
        _scrivi("clienti", n)
        return True


def richiami_di_oggi() -> list[dict]:
    oggi = _oggi().isoformat()
    return [c for c in clienti() if c.get("richiamo") and c["richiamo"] <= oggi and c["stato"] not in ("cliente", "perso")]


def sincronizza_demo() -> int:
    """Ogni demo pronta di Siti web diventa un cliente in stato «Demo pronta» (se non c'è già)."""
    try:
        import siti
        demo = siti.elenco()
    except Exception:
        return 0
    nuovi = 0
    presenti = {c.get("demo_slug") for c in clienti()}
    for m in demo:
        if m.get("stato") != "pronta" or m.get("slug") in presenti:
            continue
        tel = ""
        try:
            d = json.loads((siti.CARTELLA / m["slug"] / "dati.json").read_text(encoding="utf-8"))
            tel = d.get("telefono", "")
        except Exception:
            pass
        c, err = aggiungi_cliente(m.get("nome", m["slug"]), m.get("citta", ""), m.get("categoria", ""), telefono=tel,
                                  stato="demo", demo_slug=m["slug"])
        if c:
            nuovi += 1
        elif "già" in err:          # stesso nome già inserito a mano: collego la demo
            esist = next((x for x in clienti() if x["nome"].lower() == m.get("nome", "").lower()), None)
            if esist and not esist.get("demo_slug"):
                aggiorna_cliente(esist["id"], demo_slug=m["slug"])
    return nuovi


TIPI_MESSAGGIO = {
    "primo": "primo contatto: presenta la demo gratuita, chiedi 5 minuti per mostrarla",
    "richiamo": "richiamo cortese dopo qualche giorno senza risposta, breve, senza insistere",
    "risposta": "risposta a chi si è mostrato interessato: proponi i prossimi passi e un appuntamento",
    "preventivo": "accompagna il preventivo: riassumi cosa è incluso e chiedi conferma",
}


def prepara_messaggio(id_, tipo: str = "primo", canale: str = "whatsapp", nota: str = "") -> dict:
    """Prepara il testo (non lo invia mai). canale: whatsapp | email | telefono (traccia per la chiamata)."""
    c = cliente(id_)
    if not c:
        return {"errore": "Cliente non trovato."}
    tipo = tipo if tipo in TIPI_MESSAGGIO else "primo"
    nome = os.getenv("NOME_UTENTE", "Jonatan")
    dati = {k: c.get(k) for k in ("nome", "citta", "categoria", "stato", "link_demo", "note")}
    dati["storia_recente"] = [s["testo"] for s in c.get("storia", [])[-5:]]
    forma = {"whatsapp": "messaggio WhatsApp di 3-5 righe, tono cordiale e professionale, niente emoji",
             "email": "email breve con riga 'Oggetto:' all'inizio",
             "telefono": "traccia per una telefonata di 1 minuto: apertura, motivo, domanda finale"}.get(canale, "messaggio breve")
    system = (_regole_scrittura() + f" Sei il Commerciale di {nome}. Scrivi in prima persona come {nome}. "
              "Usa il link della demo solo se presente nei dati. Rispetta la persona: niente pressione, niente urgenze false.")
    testo = _modello(system, f"Scopo: {TIPI_MESSAGGIO[tipo]}. Forma: {forma}.\n"
                             + (f"Indicazione di {nome}: {_t(nota, 300)}\n" if nota else "")
                             + memoria.contesto(f"{c['nome']} {c.get('categoria','')} messaggio cliente")
                             + "\n\nDati del cliente:\n" + json.dumps(dati, ensure_ascii=False),
                     max_tokens=800, cliente=c["id"])
    aggiorna_cliente(c["id"], nota=f"Preparato messaggio ({tipo}, {canale})")
    return {"testo": testo, "cliente": c["nome"], "tipo": tipo, "canale": canale}


# ================================================================= CONTENUTI

def contenuti() -> list[dict]:
    return list(reversed(_leggi("contenuti")))


def crea_contenuto(tipo: str, argomento: str, cliente_id=None, nota: str = "", potenza: int | None = None) -> dict:
    argomento = _t(argomento, 400)
    if not argomento:
        return {"errore": "Serve l'argomento del contenuto."}
    if tipo not in TIPI_CONTENUTO:
        tipo = TIPI_CONTENUTO[0]
    c = cliente(cliente_id) if cliente_id not in (None, "") else None
    potenza = _potenza(potenza)
    per_chi = (f"per l'attività {c['nome']} ({c.get('categoria') or 'attività locale'}, {c.get('citta') or ''}): "
               "scrivi con la sua voce, non con quella di Jonatan") if c else "per il profilo di Jonatan"
    formato = {
        "Post social": "post per Instagram/Facebook: gancio nella prima riga, 60-120 parole, 3-6 hashtag pertinenti in fondo",
        "Post LinkedIn": "post LinkedIn: gancio, 120-220 parole, paragrafi brevi, domanda o invito finale",
        "Newsletter": "newsletter con 'Oggetto:' e anteprima, 250-400 parole, un solo invito all'azione",
        "Articolo SEO": "articolo SEO con titolo H1, meta description (max 155 caratteri), 600-900 parole con H2, parola chiave principale indicata in cima",
        "Thread X": "thread di 5-8 messaggi numerati, ognuno sotto 270 caratteri",
        "Script video": "script per video breve (45-60 secondi): scene numerate con testo parlato e cosa si vede",
        "Descrizione Google Business": "descrizione per la scheda Google Business Profile, massimo 750 caratteri, niente link né prezzi",
    }[tipo]
    system = _regole_scrittura() + " Sei la squadra Contenuti di Jarvis."
    richiesta = (f"Crea un {tipo} {per_chi}. Formato: {formato}.\nArgomento: {argomento}\n"
                 + (f"Indicazioni: {_t(nota, 400)}\n" if nota else "")
                 + memoria.contesto(f"{tipo} {argomento} {c['nome'] if c else ''}")
                 + ("\nDati del cliente: " + json.dumps({k: c.get(k) for k in ("nome", "categoria", "citta", "note")}, ensure_ascii=False) if c else ""))
    ricerca = tipo == "Articolo SEO" and potenza >= 60
    if ricerca:
        richiesta += "\nPrima verifica sul web i fatti che usi e cita le fonti in fondo in una sezione «Fonti»."
    testo = _modello(system, richiesta, max_tokens=900 + 30 * potenza, cliente=c["id"] if c else None, ricerca=ricerca)
    with _lock:
        l = _leggi("contenuti")
        x = {"id": _nuovo_id(l), "tipo": tipo, "argomento": argomento, "cliente_id": c["id"] if c else None,
             "cliente": c["nome"] if c else "", "testo": testo, "stato": "bozza", "creato": _ora(), "potenza": potenza}
        l.append(x)
        _scrivi("contenuti", l[-500:])
    if c and c.get("progetto_id"):
        _salva_in_progetto(c["progetto_id"], f"contenuto-{x['id']}-{_slug(tipo)}.md", f"# {tipo}: {argomento}\n\n{testo}\n", "Contenuti")
    return x


def aggiorna_contenuto(id_, stato=None, testo=None) -> dict | None:
    with _lock:
        l = _leggi("contenuti")
        x = next((c for c in l if c["id"] == int(id_)), None)
        if not x:
            return None
        if stato in ("bozza", "approvato", "pubblicato"):
            x["stato"] = stato
        if testo:
            x["testo"] = str(testo)[:20000]
        _scrivi("contenuti", l)
        return x


def elimina_contenuto(id_) -> bool:
    with _lock:
        l = _leggi("contenuti")
        n = [c for c in l if c["id"] != int(id_)]
        _scrivi("contenuti", n)
        return len(n) != len(l)


# ---------------------------------------------------------------- contenuti ricorrenti (solo bozze, mai pubblicati)

def ricorrenti() -> list[dict]:
    return _leggi("ricorrenti")


def crea_ricorrente(cliente_id, tipo: str, quantita: int = 4, giorno: int = 1, guida: str = "") -> tuple[dict | None, str]:
    c = cliente(cliente_id)
    if not c:
        return None, "Cliente non trovato."
    if tipo not in TIPI_CONTENUTO:
        return None, "Tipo di contenuto non valido."
    quantita, giorno = max(1, min(12, int(quantita or 4))), max(1, min(28, int(giorno or 1)))
    with _lock:
        l = _leggi("ricorrenti")
        r = {"id": _nuovo_id(l), "cliente_id": c["id"], "cliente": c["nome"], "tipo": tipo, "quantita": quantita,
             "giorno": giorno, "guida": _t(guida, 400), "attivo": True, "ultimo_mese": "", "creato": _ora()}
        l.append(r)
        _scrivi("ricorrenti", l)
    return r, ""


def imposta_ricorrente(id_, attivo: bool) -> dict | None:
    with _lock:
        l = _leggi("ricorrenti")
        r = next((x for x in l if x["id"] == int(id_)), None)
        if r:
            r["attivo"] = bool(attivo)
            _scrivi("ricorrenti", l)
        return r


def _giro_ricorrenti() -> None:
    oggi = _oggi()
    mese = oggi.strftime("%Y-%m")
    for r in ricorrenti():
        if not r["attivo"] or r["ultimo_mese"] == mese or oggi.day < r["giorno"]:
            continue
        with _lock:                                   # segno subito il mese: niente doppioni se qualcosa va storto
            l = _leggi("ricorrenti")
            x = next(x for x in l if x["id"] == r["id"])
            x["ultimo_mese"] = mese
            _scrivi("ricorrenti", l)
        fatti = 0
        for n in range(r["quantita"]):
            try:
                crea_contenuto(r["tipo"], (r["guida"] or f"contenuto del mese per {r['cliente']}") +
                               f" (pezzo {n + 1} di {r['quantita']}, {oggi.strftime('%m/%Y')}: argomenti diversi tra loro)",
                               r["cliente_id"])
                fatti += 1
            except Exception as e:
                print("Ricorrenti:", e)
        try:
            import squadre
            squadre.nota("contenuti", f"Bozze del mese pronte per {r['cliente']}: {fatti} {r['tipo']}")
            import cervello
            cervello.osa(f'display notification "{fatti} bozze per {r["cliente"].replace(chr(34), "")} da approvare" with title "Jarvis · Contenuti"')
        except Exception:
            pass


def _ciclo() -> None:
    while True:
        try:
            _giro_ricorrenti()
        except Exception as e:
            print("Produttività:", e)
        time.sleep(3600)


_avviato = False


def avvia() -> None:
    global _avviato
    if not _avviato:
        _avviato = True
        threading.Thread(target=_ciclo, daemon=True).start()


# ================================================================= TESTI SU RICHIESTA (freelance)

def lavori() -> list[dict]:
    return list(reversed(_leggi("lavori")))


def crea_lavoro(servizio: str, titolo: str, brief: str, cliente_id=None) -> dict:
    titolo, brief = _t(titolo, 150), _t(brief, 6000)
    if not brief:
        return {"errore": "Serve il brief: cosa va scritto, per chi, lunghezza, tono."}
    if servizio not in SERVIZI_TESTI:
        servizio = SERVIZI_TESTI[0]
    c = cliente(cliente_id) if cliente_id not in (None, "") else None
    system = (_regole_scrittura() + " Sei la squadra Testi su richiesta di Jarvis: consegni lavori professionali su brief. "
              "Rispetta lunghezza, tono e destinatario del brief. In fondo, dopo una riga '---', elenca in 2-4 punti "
              "cosa va verificato o deciso con il cliente (solo se serve).")
    testo = _modello(system, f"Servizio: {servizio}\nTitolo: {titolo or '[senza titolo]'}\nBrief del cliente:\n{brief}\n"
                             + memoria.contesto(f"{servizio} {titolo} {brief[:200]}"),
                     max_tokens=4000, cliente=c["id"] if c else None)
    with _lock:
        l = _leggi("lavori")
        x = {"id": _nuovo_id(l), "servizio": servizio, "titolo": titolo or servizio, "brief": brief,
             "cliente_id": c["id"] if c else None, "cliente": c["nome"] if c else "", "stato": "bozza",
             "versioni": [{"n": 1, "ts": _ora(), "testo": testo, "feedback": ""}], "creato": _ora()}
        l.append(x)
        _scrivi("lavori", l[-300:])
    _salva_versione(x)
    return x


def rivedi_lavoro(id_, feedback: str) -> dict:
    feedback = _t(feedback, 2000)
    with _lock:
        x = next((l for l in _leggi("lavori") if l["id"] == int(id_)), None)
    if not x:
        return {"errore": "Lavoro non trovato."}
    if not feedback:
        return {"errore": "Scrivi cosa cambiare."}
    ultima = x["versioni"][-1]["testo"]
    system = _regole_scrittura() + " Sei la squadra Testi su richiesta. Applica SOLO le correzioni richieste, lascia invariato il resto."
    testo = _modello(system, f"Brief originale:\n{x['brief']}\n\nVersione attuale:\n{ultima}\n\nCorrezioni richieste:\n{feedback}",
                     max_tokens=4000, cliente=x.get("cliente_id"))
    with _lock:
        l = _leggi("lavori")
        x = next(y for y in l if y["id"] == int(id_))
        x["versioni"].append({"n": len(x["versioni"]) + 1, "ts": _ora(), "testo": testo, "feedback": feedback})
        x["stato"] = "revisione"
        _scrivi("lavori", l)
    _salva_versione(x)
    return x


def stato_lavoro(id_, stato: str) -> dict | None:
    if stato not in STATI_LAVORO:
        return None
    with _lock:
        l = _leggi("lavori")
        x = next((y for y in l if y["id"] == int(id_)), None)
        if x:
            x["stato"] = stato
            _scrivi("lavori", l)
        return x


def elimina_lavoro(id_) -> bool:
    with _lock:
        l = _leggi("lavori")
        n = [c for c in l if c["id"] != int(id_)]
        _scrivi("lavori", n)
        return len(n) != len(l)


def _salva_versione(x: dict) -> None:
    c = cliente(x.get("cliente_id")) if x.get("cliente_id") else None
    if c and c.get("progetto_id"):
        v = x["versioni"][-1]
        _salva_in_progetto(c["progetto_id"], f"lavoro-{x['id']}-v{v['n']}.md",
                           f"# {x['titolo']} ({x['servizio']}) – versione {v['n']}\n\n{v['testo']}\n", "Lavori")


# ================================================================= AMMINISTRAZIONE: listino, preventivi, abbonamenti, incassi

def listino() -> list[dict]:
    with _lock:
        l = _leggi("listino")
        if not l:
            l = [dict(v) for v in LISTINO_BASE]
            _scrivi("listino", l)
        else:                                          # aggiunge le voci nuove senza toccare i prezzi già scelti
            ids = {v["id"] for v in l}
            nuove = [dict(v) for v in LISTINO_BASE if v["id"] not in ids]
            if nuove:
                l += nuove
                _scrivi("listino", l)
        return l


def voce(id_) -> dict | None:
    return next((v for v in listino() if v["id"] == id_), None)


def aggiorna_voce(id_, prezzo=None, nome=None, unita=None, nuova=False, gruppo="Altro") -> tuple[dict | None, str]:
    with _lock:
        l = listino()
        v = next((x for x in l if x["id"] == id_), None)
        if not v:
            if not nuova or not nome:
                return None, "Voce del listino non trovata."
            v = {"id": re.sub(r"[^a-z0-9-]+", "-", _t(nome, 60).lower()).strip("-") or uuid.uuid4().hex[:6],
                 "gruppo": _t(gruppo, 40) or "Altro", "nome": _t(nome, 80), "prezzo": None, "unita": "una tantum"}
            l.append(v)
        if prezzo is not None:
            if prezzo == "":
                v["prezzo"] = None
            else:
                try:
                    p = float(str(prezzo).replace("€", "").replace(",", ".").strip())
                except ValueError:
                    return None, "Prezzo non valido."
                if not 0 <= p <= 100000:
                    return None, "Prezzo fuori scala."
                v["prezzo"] = round(p, 2)
        if nome:
            v["nome"] = _t(nome, 80)
        if unita in ("una tantum", "mese", "pezzo", "ora"):
            v["unita"] = unita
        _scrivi("listino", l)
        return v, ""


def testo_listino() -> str:
    return "\n".join(f"{v['id']}: {v['nome']} – {_euro(v['prezzo'])}" + ("" if v["unita"] == "una tantum" else f" / {v['unita']}")
                     for v in listino()) + "\nPrezzi IVA esclusa."


def preventivi() -> list[dict]:
    return list(reversed(_leggi("preventivi")))


def preventivo(id_) -> dict | None:
    return next((p for p in _leggi("preventivi") if p["id"] == int(id_)), None)


def _totali(righe) -> dict:
    una = sum((r["prezzo"] or 0) * r["quantita"] for r in righe if r["unita"] != "mese")
    mese = sum((r["prezzo"] or 0) * r["quantita"] for r in righe if r["unita"] == "mese")
    return {"una_tantum": round(una, 2), "mensile": round(mese, 2),
            "da_decidere": any(r["prezzo"] is None for r in righe)}


def crea_preventivo(cliente_id, voci: list, note: str = "") -> tuple[dict | None, str]:
    """voci: lista di id del listino oppure di {"id":..., "quantita":..., "prezzo": facoltativo per uno sconto}."""
    c = cliente(cliente_id)
    if not c:
        return None, "Cliente non trovato: aggiungilo prima ai clienti."
    righe = []
    for v in voci or []:
        vid, q, prezzo = (v, 1, None) if isinstance(v, str) else (v.get("id"), v.get("quantita", 1), v.get("prezzo"))
        x = voce(vid)
        if not x:
            return None, f"Voce «{vid}» non presente nel listino."
        try:
            q = max(1, min(100, int(q or 1)))
        except (TypeError, ValueError):
            q = 1
        p = x["prezzo"]
        if prezzo not in (None, ""):
            try:
                p = round(float(str(prezzo).replace(",", ".")), 2)
            except ValueError:
                pass
        righe.append({"voce": x["id"], "descrizione": x["nome"], "quantita": q, "prezzo": p, "unita": x["unita"]})
    if not righe:
        return None, "Indica almeno una voce del listino."
    with _lock:
        l = _leggi("preventivi")
        anno = _oggi().year
        n = sum(1 for p in l if p["numero"].startswith(f"{anno}-")) + 1
        p = {"id": _nuovo_id(l), "numero": f"{anno}-{n:03d}", "cliente_id": c["id"], "cliente": c["nome"],
             "righe": righe, "note": _t(note, 1500), "stato": "bozza", "link_pagamento": "",
             "creato": _ora(), "valido_fino": (_oggi() + dt.timedelta(days=30)).isoformat(), "storia": []}
        p.update(_totali(righe))
        l.append(p)
        _scrivi("preventivi", l)
    if c["stato"] in ("trovato", "demo", "contattato", "risposta"):
        aggiorna_cliente(c["id"], stato="trattativa", nota=f"Preventivo {p['numero']} preparato")
    if c.get("progetto_id"):
        _salva_in_progetto(c["progetto_id"], f"preventivo-{p['numero']}.md", preventivo_md(p), "Preventivo")
    return p, ""


def aggiorna_preventivo(id_, stato=None, link_pagamento=None, note=None) -> tuple[dict | None, str]:
    with _lock:
        l = _leggi("preventivi")
        p = next((x for x in l if x["id"] == int(id_)), None)
        if not p:
            return None, "Preventivo non trovato."
        if link_pagamento is not None:
            lp = str(link_pagamento).strip()
            if lp and not re.match(r"^https://[^\s]+$", lp):
                return None, "Il link di pagamento deve iniziare con https://"
            p["link_pagamento"] = lp[:400]
        if note is not None:
            p["note"] = _t(note, 1500)
        if stato and stato != p["stato"]:
            if stato not in STATI_PREVENTIVO:
                return None, "Stato non valido."
            if stato in ("inviato", "accettato", "pagato") and p.get("da_decidere"):
                return None, "Ci sono prezzi «da decidere»: completali nel listino e rifai il preventivo."
            p["storia"].append({"ts": _ora(), "testo": f"{p['stato']} → {stato}"})
            vecchio, p["stato"] = p["stato"], stato
        else:
            vecchio = None
        _scrivi("preventivi", l)
    if vecchio is not None:
        if stato == "accettato" or (stato == "pagato" and vecchio != "accettato"):
            _attiva_abbonamenti(p)
            aggiorna_cliente(p["cliente_id"], stato="cliente", nota=f"Preventivo {p['numero']} accettato")
        if stato == "pagato" and p["una_tantum"] > 0:
            registra_incasso(p["cliente_id"], p["una_tantum"], f"Preventivo {p['numero']}", fonte=f"preventivo:{p['id']}")
        if stato == "rifiutato":
            aggiorna_cliente(p["cliente_id"], nota=f"Preventivo {p['numero']} rifiutato")
    return p, ""


def preventivo_md(p: dict) -> str:
    nome = os.getenv("NOME_UTENTE", "Jonatan")
    r = [f"# Preventivo {p['numero']}", "", f"Per: **{p['cliente']}**  ", f"Da: {nome}  ",
         f"Data: {p['creato'][:10]} · valido fino al {p['valido_fino']}", "", "| Voce | Q.tà | Prezzo |", "|---|---|---|"]
    for x in p["righe"]:
        r.append(f"| {x['descrizione']} | {x['quantita']} | {_euro(x['prezzo'])}{' / mese' if x['unita'] == 'mese' else ''} |")
    r += ["", f"**Totale una tantum: {_euro(p['una_tantum'])}**"]
    if p["mensile"]:
        r.append(f"**Canone mensile: {_euro(p['mensile'])}**")
    r += ["", "Prezzi IVA esclusa."]
    if p.get("note"):
        r += ["", p["note"]]
    if p.get("link_pagamento"):
        r += ["", f"Pagamento: {p['link_pagamento']}"]
    return "\n".join(r) + "\n"


def abbonamenti() -> list[dict]:
    return _leggi("abbonamenti")


def _attiva_abbonamenti(p: dict) -> None:
    with _lock:
        l = _leggi("abbonamenti")
        for r in p["righe"]:
            if r["unita"] != "mese" or any(a.get("fonte") == f"preventivo:{p['id']}:{r['voce']}" for a in l):
                continue
            l.append({"id": _nuovo_id(l), "cliente_id": p["cliente_id"], "cliente": p["cliente"],
                      "descrizione": r["descrizione"], "prezzo_mese": (r["prezzo"] or 0) * r["quantita"],
                      "inizio": _oggi().isoformat(), "stato": "attivo", "pagato_fino": "",
                      "fonte": f"preventivo:{p['id']}:{r['voce']}"})
        _scrivi("abbonamenti", l)


def crea_abbonamento(cliente_id, descrizione: str, prezzo_mese) -> tuple[dict | None, str]:
    c = cliente(cliente_id)
    if not c:
        return None, "Cliente non trovato."
    try:
        prezzo = round(float(str(prezzo_mese).replace(",", ".")), 2)
    except ValueError:
        return None, "Prezzo non valido."
    with _lock:
        l = _leggi("abbonamenti")
        a = {"id": _nuovo_id(l), "cliente_id": c["id"], "cliente": c["nome"], "descrizione": _t(descrizione, 100),
             "prezzo_mese": prezzo, "inizio": _oggi().isoformat(), "stato": "attivo", "pagato_fino": "", "fonte": "manuale"}
        l.append(a)
        _scrivi("abbonamenti", l)
    return a, ""


def abbonamento_pagato(id_) -> tuple[dict | None, str]:
    """Segna pagato il mese successivo all'ultimo pagato e registra l'incasso."""
    with _lock:
        l = _leggi("abbonamenti")
        a = next((x for x in l if x["id"] == int(id_)), None)
        if not a:
            return None, "Abbonamento non trovato."
        base = dt.date.fromisoformat(a["pagato_fino"] + "-01") if a["pagato_fino"] else dt.date.fromisoformat(a["inizio"]).replace(day=1) - dt.timedelta(days=1)
        prossimo = (base.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        a["pagato_fino"] = prossimo.strftime("%Y-%m")
        _scrivi("abbonamenti", l)
    registra_incasso(a["cliente_id"], a["prezzo_mese"], f"{a['descrizione']} – {prossimo.strftime('%m/%Y')}", fonte=f"abbonamento:{a['id']}")
    return a, ""


def stato_abbonamento(id_, stato: str) -> dict | None:
    if stato not in ("attivo", "sospeso", "chiuso"):
        return None
    with _lock:
        l = _leggi("abbonamenti")
        a = next((x for x in l if x["id"] == int(id_)), None)
        if a:
            a["stato"] = stato
            _scrivi("abbonamenti", l)
        return a


def incassi() -> list[dict]:
    return list(reversed(_leggi("incassi")))


def registra_incasso(cliente_id, importo, descrizione: str, fonte: str = "manuale", data: str = "") -> tuple[dict | None, str]:
    try:
        importo = round(float(str(importo).replace(",", ".")), 2)
    except ValueError:
        return None, "Importo non valido."
    if importo <= 0:
        return None, "L'importo deve essere positivo."
    c = cliente(cliente_id) if cliente_id not in (None, "") else None
    with _lock:
        l = _leggi("incassi")
        x = {"id": _nuovo_id(l), "data": data if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data or "") else _oggi().isoformat(),
             "cliente_id": c["id"] if c else None, "cliente": c["nome"] if c else "", "importo": importo,
             "descrizione": _t(descrizione, 150), "fonte": fonte}
        l.append(x)
        _scrivi("incassi", l)
    return x, ""


def cassa() -> dict:
    """Incassi del mese, ultimi 12 mesi, canone mensile ricorrente (MRR), preventivi aperti."""
    oggi = _oggi()
    mese = oggi.strftime("%Y-%m")
    inc = incassi()
    per_mese = {}
    for x in inc:
        per_mese[x["data"][:7]] = round(per_mese.get(x["data"][:7], 0) + x["importo"], 2)
    mesi = []
    d = oggi.replace(day=1)
    for _ in range(12):
        mesi.append({"mese": d.strftime("%Y-%m"), "totale": per_mese.get(d.strftime("%Y-%m"), 0)})
        d = (d - dt.timedelta(days=1)).replace(day=1)
    ab = [a for a in abbonamenti() if a["stato"] == "attivo"]
    da_incassare = [a for a in ab if (a["pagato_fino"] or "") < mese]
    aperti = [p for p in preventivi() if p["stato"] in ("bozza", "inviato", "accettato")]
    return {"mese": mese, "incassato_mese": per_mese.get(mese, 0), "mesi": list(reversed(mesi)),
            "mrr": round(sum(a["prezzo_mese"] for a in ab), 2), "abbonamenti_attivi": len(ab),
            "abbonamenti_da_incassare": [{"id": a["id"], "cliente": a["cliente"], "descrizione": a["descrizione"],
                                          "prezzo_mese": a["prezzo_mese"]} for a in da_incassare],
            "preventivi_aperti": len(aperti),
            "valore_preventivi_aperti": round(sum(p["una_tantum"] for p in aperti), 2)}


def margine() -> list[dict]:
    """Per cliente: incassato contro costo dell'AI (token e, se impostati i prezzi, euro)."""
    cl = clienti()
    costi = uso.costo_per({c["id"]: c.get("demo_slug") or None for c in cl})
    inc = incassi()
    out = []
    for c in cl:
        incassato = round(sum(x["importo"] for x in inc if x["cliente_id"] == c["id"]), 2)
        k = costi.get(c["id"], {})
        if not incassato and not k.get("token"):
            continue
        out.append({"cliente_id": c["id"], "cliente": c["nome"], "stato": c["stato"], "incassato": incassato,
                    "token": k.get("token", 0), "ricerche": k.get("ricerche", 0), "costo_ai": k.get("costo"),
                    "margine": round(incassato - k["costo"], 2) if k.get("costo") is not None else None})
    return sorted(out, key=lambda x: x["incassato"], reverse=True)


# ================================================================= POTENZA

def _potenza(p=None) -> int:
    if p not in (None, ""):
        try:
            return max(1, min(100, int(p)))
        except (TypeError, ValueError):
            pass
    try:
        import impostazioni
        return int(impostazioni.carica().get("potenza", 50))
    except Exception:
        return 50


# ================================================================= utilità

def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40]


def _salva_in_progetto(progetto_id, nome_file: str, testo: str, cartella_pref: str = "") -> None:
    """Aggiunge un file nella cartella del progetto (mai sovrascrive) e lascia una riga di registro."""
    try:
        import progetti
        p = progetti.dettaglio(progetto_id)
        if not p:
            return
        base = Path(p["percorso"])
        sotto = next((d for d in sorted(base.iterdir()) if d.is_dir() and cartella_pref.lower() in d.name.lower()), base) \
            if cartella_pref and base.is_dir() else base
        f = sotto / nome_file
        n = 2
        while f.exists():
            f = sotto / f"{Path(nome_file).stem}-{n}{Path(nome_file).suffix}"
            n += 1
        f.write_text(testo, encoding="utf-8")
        progetti.registra(progetto_id, "produttivita", f"Aggiunto {f.relative_to(base)}")
    except Exception as e:
        print("Produttività, progetto:", e)


def panoramica() -> dict:
    sincronizza_demo()
    cl = clienti()
    conti = {s: 0 for s in CHIAVI_STATO}
    for c in cl:
        conti[c["stato"]] = conti.get(c["stato"], 0) + 1
    return {"pipeline": [{"stato": s, "nome": n, "n": conti.get(s, 0)} for s, n in STATI_CLIENTE],
            "richiami_oggi": [{"id": c["id"], "nome": c["nome"], "stato": c["stato"], "richiamo": c["richiamo"],
                               "telefono": c.get("telefono", "")} for c in richiami_di_oggi()],
            "cassa": cassa(), "contenuti_da_approvare": sum(1 for x in contenuti() if x["stato"] == "bozza"),
            "lavori_aperti": sum(1 for x in lavori() if x["stato"] != "consegnato"),
            "prezzi_da_decidere": sum(1 for v in listino() if v["prezzo"] is None),
            "jobs": jobs_in_corso(), "potenza": _potenza()}


def testo_per_jarvis() -> str:
    p = panoramica()
    pipe = ", ".join(f"{x['nome']} {x['n']}" for x in p["pipeline"] if x["n"])
    r = [f"Clienti: {pipe or 'nessuno'}."]
    if p["richiami_oggi"]:
        r.append("Da richiamare oggi: " + ", ".join(f"{c['nome']} (#{c['id']})" for c in p["richiami_oggi"]) + ".")
    k = p["cassa"]
    r.append(f"Incassato questo mese {_euro(k['incassato_mese'])}, canoni mensili attivi {_euro(k['mrr'])} "
             f"({k['abbonamenti_attivi']} abbonamenti), preventivi aperti {k['preventivi_aperti']}.")
    if k["abbonamenti_da_incassare"]:
        r.append("Canoni del mese ancora da incassare: " + ", ".join(a["cliente"] for a in k["abbonamenti_da_incassare"]) + ".")
    if p["contenuti_da_approvare"]:
        r.append(f"Contenuti in bozza da approvare: {p['contenuti_da_approvare']}.")
    if p["lavori_aperti"]:
        r.append(f"Lavori su richiesta aperti: {p['lavori_aperti']}.")
    return " ".join(r)


def elenco_clienti_testo(stato: str = "") -> str:
    l = [c for c in clienti() if not stato or c["stato"] == stato]
    if not l:
        return "Nessun cliente" + (f" in stato {stato}." if stato else ".")
    return "\n".join(f"#{c['id']} {c['nome']} ({c.get('citta') or '-'}) · {dict(STATI_CLIENTE)[c['stato']]}"
                     + (f" · richiamo {c['richiamo']}" if c.get("richiamo") else "")
                     + (f" · demo {c['demo_slug']}" if c.get("demo_slug") else "") for c in l[:40])
