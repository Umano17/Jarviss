"""Approvazioni: le azioni critiche partono solo dopo un SÌ di Jonatan, anche quando non è davanti al Mac.

Come funziona:
  1. Uno strumento critico (es. creare un evento, pubblicare una demo, inviare un'email, riattivare il trader)
     non esegue subito: chiama richiedi(azione, argomenti, descrizione).
  2. Jarvis manda su Telegram il messaggio con due pulsanti: SÌ e NO (vale anche rispondere «sì» o «no»).
     La stessa richiesta compare sulla schermata nella coda «Da approvare».
  3. SÌ → l'azione viene eseguita e su Telegram arriva l'esito. NO → annullata. Senza risposta scade.

Zona sacra (3.7): una richiesta con sacra=True (es. un aggiornamento che tocca i file di zona_sacra.py) dopo il SÌ
non parte subito: Jarvis manda su Telegram un codice casuale di 6 cifre, valido una volta e per 5 minuti.
Si riscrive il codice (su Telegram o sulla schermata) e solo allora l'azione viene eseguita. 3 codici sbagliati
o 5 minuti senza codice = richiesta annullata, con avviso.

Solo chi scrive dal TELEGRAM_CHAT_ID di Jonatan o dalla schermata sul Mac può rispondere.
Il modello (Claude) NON può approvare da solo: nessuno strumento di Jarvis decide un'approvazione.
Dati in dati/approvazioni.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

FILE = Path(__file__).parent / "dati" / "approvazioni.json"
_lock = threading.RLock()
SCADENZA_ORE = 12
CODICE_MINUTI = 5
CODICE_TENTATIVI = 3

# azione -> funzione che la esegue (registrata dai moduli che la possiedono)
_AZIONI: dict[str, callable] = {}
_RIFIUTO: dict[str, callable] = {}     # facoltativo: cosa fare se la risposta è NO o se scade


def registra(azione: str, esegui, al_rifiuto=None) -> None:
    _AZIONI[azione] = esegui
    if al_rifiuto:
        _RIFIUTO[azione] = al_rifiuto


def _leggi() -> list[dict]:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _scrivi(l: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(l[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)


def _ora() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _tg():
    try:
        from segreteria import telegram_bot
        return telegram_bot if telegram_bot.configurato() else None
    except Exception:
        return None


# ---------------------------------------------------------------- richiesta

def richiedi(azione: str, argomenti: dict, descrizione: str, scadenza_ore: float = SCADENZA_ORE,
             chiave: str = "", sacra: bool = False) -> dict:
    """Mette in attesa un'azione critica e chiede SÌ/NO su Telegram. chiave = evita doppioni della stessa richiesta.
    sacra=True: dopo il SÌ serve anche il codice di verifica mandato su Telegram."""
    if azione not in _AZIONI:
        raise ValueError(f"Azione «{azione}» non registrata per le approvazioni.")
    with _lock:
        l = _leggi()
        if chiave:
            uguale = next((x for x in l if x["stato"] == "in_attesa" and x.get("chiave") == chiave), None)
            if uguale:
                return uguale
        a = {"id": max((x["id"] for x in l), default=0) + 1, "azione": azione, "argomenti": argomenti,
             "descrizione": descrizione[:900], "stato": "in_attesa", "creata": _ora(),
             "scade": time.time() + scadenza_ore * 3600, "chiave": chiave, "esito": "", "deciso_da": "",
             "tg_msg": None, "sacra": bool(sacra)}
        l.append(a)
        _scrivi(l)
    bot = _tg()
    if bot:
        testa = (f"🛡️ ZONA SACRA – Richiesta n.{a['id']}: dopo il SÌ ti mando un codice di verifica"
                 if sacra else f"🔐 Richiesta n.{a['id']} – serve il tuo sì")
        mid = bot.chiedi_si_no(f"{testa}\n\n{a['descrizione']}", a["id"])
        if mid:
            _aggiorna(a["id"], tg_msg=mid)
    return a


def _aggiorna(id_: int, **campi) -> dict | None:
    with _lock:
        l = _leggi()
        a = next((x for x in l if x["id"] == int(id_)), None)
        if a:
            a.update(campi)
            _scrivi(l)
        return a


# ---------------------------------------------------------------- decisione

def decidi(id_: int, si: bool, da: str = "schermo") -> str:
    """SÌ o NO di Jonatan (da Telegram o dalla schermata). Restituisce il testo dell'esito."""
    with _lock:
        _scadute()
        a = next((x for x in _leggi() if x["id"] == int(id_)), None)
        if not a:
            return "Richiesta non trovata."
        if a["stato"] == "attesa_codice" and si:
            return f"Per la richiesta n.{a['id']} aspetto il codice di verifica di 6 cifre che ti ho mandato su Telegram."
        if a["stato"] not in ("in_attesa", "attesa_codice"):
            return f"La richiesta n.{a['id']} è già {a['stato'].replace('_', ' ')}."
        if si and a.get("sacra"):
            return _chiedi_codice(a, da)
        _aggiorna(a["id"], stato="in_esecuzione" if si else "rifiutata", deciso_da=da, decisa=_ora())
    if not si:
        try:
            if a["azione"] in _RIFIUTO:
                _RIFIUTO[a["azione"]](**a["argomenti"])
        except Exception as e:
            print("Approvazioni, rifiuto:", repr(e))
        esito = f"Annullato: {_titolo(a)}."
        _aggiorna(a["id"], esito=esito)
        _diario(f"NO di Jonatan ({da}): {_titolo(a)}", "info")
        _chiudi_messaggio(a, "❌ NO – " + esito)
        return esito
    return _esegui(a)


def _esegui(a: dict) -> str:
    try:
        esito = str(_AZIONI[a["azione"]](**a["argomenti"]) or "Fatto.")
        stato = "approvata"
    except Exception as e:
        print("Approvazioni, esecuzione:", repr(e))
        esito, stato = f"Approvato, ma l'azione non è riuscita: {str(e)[:200]}", "errore"
    _aggiorna(a["id"], stato=stato, esito=esito[:600])
    _chiudi_messaggio(a, ("✅ SÌ – " if stato == "approvata" else "⚠️ ") + esito)
    _diario(f"Approvato: {_titolo(a)} – {esito[:120]}", "ok" if stato == "approvata" else "errore")
    return esito


def _diario(testo: str, tipo: str = "info") -> None:
    try:
        import attivita
        attivita.registra(testo, "approvazioni", tipo)
    except Exception:
        pass


# ---------------------------------------------------------------- codice di verifica (zona sacra)

def _impronta(sale: str, codice: str) -> str:
    return hashlib.sha256((sale + codice).encode()).hexdigest()


def _chiedi_codice(a: dict, da: str) -> str:
    """Dopo il SÌ a una richiesta sacra: codice casuale di 6 cifre su Telegram (mai salvato in chiaro)."""
    bot = _tg()
    if not bot:
        return ("Questa è una modifica della zona sacra: serve il codice di verifica su Telegram, ma Telegram non è "
                "configurato. Non ho fatto nulla.")
    codice = f"{secrets.randbelow(10 ** 6):06d}"
    sale = secrets.token_hex(8)
    _aggiorna(a["id"], stato="attesa_codice", codice_sale=sale, codice_hash=_impronta(sale, codice),
              codice_scade=time.time() + CODICE_MINUTI * 60, codice_tentativi=0, si_da=da)
    if a.get("tg_msg"):
        bot.modifica_messaggio(a["tg_msg"], f"🛡️ Richiesta n.{a['id']}\n{a['descrizione']}\n\n"
                                            "SÌ ricevuto: aspetto il codice di verifica.")
    bot.notifica(f"🔑 Codice di verifica per la richiesta n.{a['id']}: {codice}\n\n"
                 f"Scrivilo qui o sulla schermata entro {CODICE_MINUTI} minuti. Vale una volta sola. "
                 f"Dopo {CODICE_TENTATIVI} errori la richiesta viene annullata.")
    return f"Ti ho mandato il codice di verifica su Telegram: scrivilo per confermare la richiesta n.{a['id']}."


def verifica_codice(id_: int, codice: str, da: str = "schermo") -> str:
    """Controlla il codice di una richiesta sacra. Giusto = esegue; sbagliato 3 volte o scaduto = annulla."""
    codice = re.sub(r"\D", "", str(codice or ""))
    with _lock:
        _scadute()
        a = next((x for x in _leggi() if x["id"] == int(id_)), None)
        if not a or a["stato"] != "attesa_codice":
            return "Non c'è nessuna richiesta che aspetta un codice."
        giusto = len(codice) == 6 and hmac.compare_digest(_impronta(a.get("codice_sale", ""), codice),
                                                          a.get("codice_hash", ""))
        if not giusto:
            n = int(a.get("codice_tentativi", 0)) + 1
            if n >= CODICE_TENTATIVI:
                _aggiorna(a["id"], stato="annullata", codice_tentativi=n, codice_hash="", decisa=_ora(),
                          esito=f"{CODICE_TENTATIVI} codici sbagliati: annullata per sicurezza.")
                _rifiuta(a)
                _chiudi_messaggio(a, f"⛔ {CODICE_TENTATIVI} codici sbagliati: richiesta annullata per sicurezza.")
                _diario(f"Zona sacra: {CODICE_TENTATIVI} codici sbagliati, annullata «{_titolo(a)}»", "avviso")
                return f"Codice sbagliato per la terza volta: ho annullato la richiesta n.{a['id']}."
            _aggiorna(a["id"], codice_tentativi=n)
            return f"Codice sbagliato. Tentativi rimasti: {CODICE_TENTATIVI - n}."
        # giusto: il codice non vale più, poi si esegue
        _aggiorna(a["id"], stato="in_esecuzione", codice_hash="", deciso_da=f"{a.get('si_da', da)}+codice:{da}",
                  decisa=_ora())
    return _esegui(a)


def _rifiuta(a: dict) -> None:
    try:
        if a["azione"] in _RIFIUTO:
            _RIFIUTO[a["azione"]](**a["argomenti"])
    except Exception as e:
        print("Approvazioni, rifiuto:", repr(e))


def _titolo(a: dict) -> str:
    return a["descrizione"].split("\n")[0][:120].rstrip(" .?!")


def _chiudi_messaggio(a: dict, testo: str) -> None:
    bot = _tg()
    if not bot:
        return
    if a.get("tg_msg"):
        bot.modifica_messaggio(a["tg_msg"], f"Richiesta n.{a['id']}\n{a['descrizione']}\n\n{testo}")
    else:
        bot.notifica(f"Richiesta n.{a['id']}: {testo}")


def _scadute() -> None:
    adesso = time.time()
    for a in _leggi():
        if a["stato"] == "attesa_codice" and a.get("codice_scade", 0) < adesso:
            _aggiorna(a["id"], stato="annullata", codice_hash="", esito="Codice non arrivato in tempo: annullata.")
            _rifiuta(a)
            _chiudi_messaggio(a, f"⌛ Codice non arrivato entro {CODICE_MINUTI} minuti: richiesta annullata.")
            continue
        if a["stato"] == "in_attesa" and a.get("scade", 0) < adesso:
            _aggiorna(a["id"], stato="scaduta", esito="Nessuna risposta: annullata.")
            try:
                if a["azione"] in _RIFIUTO:
                    _RIFIUTO[a["azione"]](**a["argomenti"])
            except Exception:
                pass
            _chiudi_messaggio(a, "⌛ Scaduta senza risposta: non ho fatto nulla.")


def in_attesa() -> list[dict]:
    with _lock:
        _scadute()
        return [{k: a[k] for k in ("id", "azione", "descrizione", "creata")} |
                {"scade_tra_min": max(0, int((a["scade"] - time.time()) / 60)), "sacra": bool(a.get("sacra")),
                 "serve_codice": a["stato"] == "attesa_codice"}
                for a in _leggi() if a["stato"] in ("in_attesa", "attesa_codice")]


def recenti(n: int = 15) -> list[dict]:
    return [{k: a.get(k) for k in ("id", "azione", "descrizione", "stato", "creata", "esito", "deciso_da")}
            for a in reversed(_leggi()[-n:])]


# ---------------------------------------------------------------- risposte scritte («sì», «no», «sì 3»)

_SI = re.compile(r"^\s*(s[iì]|ok|okay|approvo|confermo|vai)\b[\s.!]*(?:n\.?\s*)?(\d+)?\s*[.!]*\s*$", re.I)
_CODICE = re.compile(r"^\s*(\d{3}\s?\d{3})\s*$")
_NO = re.compile(r"^\s*(no|annulla|rifiuto|stop)\b[\s.!]*(?:n\.?\s*)?(\d+)?\s*[.!]*\s*$", re.I)


def risposta_testo(testo: str, da: str, entro_min: int | None = None) -> str | None:
    """Se il messaggio è un SÌ/NO per una richiesta in attesa, la decide e restituisce l'esito; altrimenti None.
    entro_min: considera solo le richieste nate negli ultimi N minuti (sulla schermata un «no» detto in una
    conversazione qualsiasi non deve annullare una richiesta vecchia)."""
    m_cod = _CODICE.match(testo or "")
    if m_cod:
        aspettano = [a for a in in_attesa() if a["serve_codice"]]
        if aspettano:
            return verifica_codice(aspettano[-1]["id"], m_cod.group(1), da)
    m_si, m_no = _SI.match(testo or ""), _NO.match(testo or "")
    if not (m_si or m_no):
        return None
    attesa = in_attesa()
    if entro_min is not None:
        limite = (dt.datetime.now() - dt.timedelta(minutes=entro_min)).strftime("%Y-%m-%d %H:%M")
        attesa = [a for a in attesa if a["creata"] >= limite]
    if not attesa:
        return None
    numero = (m_si or m_no).group(2)
    if numero:
        id_ = int(numero)
        if not any(a["id"] == id_ for a in attesa):
            return f"Non c'è nessuna richiesta n.{id_} in attesa."
    elif len(attesa) == 1:
        id_ = attesa[0]["id"]
    else:
        return ("Ci sono più richieste in attesa: " + ", ".join(f"n.{a['id']}" for a in attesa) +
                ". Usa i pulsanti SÌ / NO oppure scrivi per esempio «sì " + str(attesa[0]["id"]) + "».")
    return decidi(id_, bool(m_si), da)


def chiudi(chiave: str, esito: str) -> None:
    """Chiude una richiesta in attesa decisa per altra via (es. email inviata dicendo «invia» a voce)."""
    with _lock:
        a = next((x for x in _leggi() if x["stato"] == "in_attesa" and x.get("chiave") == chiave), None)
    if a:
        _aggiorna(a["id"], stato="chiusa", esito=esito, decisa=_ora())
        _chiudi_messaggio(a, "ℹ️ " + esito)


def chiudi_id(id_: int, esito: str) -> None:
    a = _aggiorna(id_, stato="chiusa", esito=esito, decisa=_ora())
    if a:
        _chiudi_messaggio(a, "ℹ️ " + esito)
