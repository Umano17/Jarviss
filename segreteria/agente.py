"""Il cervello della Segreteria.

gestisci(testo) riceve una frase (detta a voce o scritta su Telegram):
- se riguarda le email, la gestisce e restituisce la risposta da dare;
- altrimenti restituisce None e la frase va a Jarvis come sempre.
Nessuna email parte senza la parola "invia".
"""
import re, threading, time
from .config import RUBRICA
try:
    import rubrica
except Exception:     # prova da sola, fuori da Jarvis
    rubrica = None
from .email_gmail import componi, crea_bozza, invia_bozza, elimina_bozza
from .google_account import salva_su_drive

_lock = threading.Lock()
_stato = {"bozza": None, "attesa_indirizzo": None}
SCADENZA_SECONDI = 12 * 3600   # una bozza non confermata scade dopo 12 ore (si può approvare da Telegram)

NUOVA_EMAIL = re.compile(r"\b(scrivi|manda|invia|prepara)\b.*\b(e-?mail|mail)\b", re.I)
MODIFICA = re.compile(r"^\s*(modifica|cambia|correggi)\b", re.I)

def _trova_indirizzo(nome):
    d = (nome or "").strip().lower()
    if "@" in d:
        return d.replace(" ", "")
    if rubrica:
        trovato = rubrica.trova_email(d)
        if trovato:
            return trovato
    return RUBRICA.get(d)

def _indirizzo_parlato(testo):
    t = (" " + testo.lower() + " ").replace(" chiocciola ", "@").replace(" punto ", ".")
    t = t.replace(" ", "")
    return t if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", t) else None

def _leggi(b):
    return (f"Bozza per {b['indirizzo']}. Oggetto: {b['oggetto']}. Testo: {b['testo']} "
            "Rispondi invia, annulla, oppure modifica seguito da cosa cambiare.")

def _prepara(indirizzo, bozza, richiesta):
    if rubrica and rubrica.bloccato(indirizzo):
        return (f"{indirizzo} è segnato come non contattare nella Rubrica: non scrivo. "
                "Se è un errore, togli il segno dal contatto.")
    id_b = crea_bozza(indirizzo, bozza["oggetto"], bozza["testo"])
    _stato["bozza"] = {"id": id_b, "indirizzo": indirizzo, "oggetto": bozza["oggetto"],
                       "testo": bozza["testo"], "richiesta": richiesta, "ora": time.time()}
    _chiedi_approvazione(_stato["bozza"])
    return _leggi(_stato["bozza"])


def _chiedi_approvazione(b):
    """La stessa bozza arriva su Telegram con SÌ / NO: si può approvare anche lontano dal Mac."""
    try:
        import approvazioni
        for vecchia in approvazioni.in_attesa():          # una sola bozza alla volta: le precedenti decadono
            if vecchia["azione"] == "email_invia":
                approvazioni.chiudi_id(vecchia["id"], "Sostituita da una nuova bozza.")
        approvazioni.richiedi("email_invia", {"bozza_id": b["id"]},
                              f"Inviare questa email?\nA: {b['indirizzo']}\nOggetto: {b['oggetto']}\n\n{b['testo'][:2500]}",
                              scadenza_ore=SCADENZA_SECONDI / 3600, chiave=f"email:{b['id']}")
    except Exception as e:
        print("Segreteria, approvazione:", repr(e))


def _chiudi_approvazione(b, esito):
    try:
        import approvazioni
        approvazioni.chiudi(f"email:{b['id']}", esito)
    except Exception:
        pass


def _approva_da_richiesta(bozza_id):
    with _lock:
        b = _bozza_valida()
        if not b or b["id"] != bozza_id:
            return "Questa bozza non è più in attesa (inviata, annullata o sostituita)."
        return _invia(b, chiudi=False)


def _scarta_da_richiesta(bozza_id):
    with _lock:
        b = _stato["bozza"]
        if b and b["id"] == bozza_id:
            elimina_bozza(b["id"])
            _stato["bozza"] = None


try:
    import approvazioni as _ap
    _ap.registra("email_invia", _approva_da_richiesta, _scarta_da_richiesta)
except Exception:
    pass

def _invia(b, chiudi=True):
    invia_bozza(b["id"])
    _stato["bozza"] = None
    if chiudi:
        _chiudi_approvazione(b, f"Email inviata a {b['indirizzo']} (approvata dalla schermata o a voce).")
    salva_su_drive(f"Email a {b['indirizzo']} {time.strftime('%Y-%m-%d %H-%M')}.txt",
                   f"A: {b['indirizzo']}\nOggetto: {b['oggetto']}\n\n{b['testo']}")
    return f"Email inviata a {b['indirizzo']}."


def _bozza_valida():
    b = _stato["bozza"]
    if b and time.time() - b["ora"] > SCADENZA_SECONDI:
        elimina_bozza(b["id"])
        _stato["bozza"] = b = None
    return b


def bozza_in_attesa():
    """La bozza che aspetta il tuo sì (per la coda 'Da approvare'), oppure None."""
    with _lock:
        b = _bozza_valida()
        if not b:
            return None
        return {"indirizzo": b["indirizzo"], "oggetto": b["oggetto"], "testo": b["testo"],
                "scade_tra": max(0, int(SCADENZA_SECONDI - (time.time() - b["ora"])))}


def approva():
    """Invia la bozza in attesa. Si usa solo dal pulsante nella schermata (decide l'utente)."""
    with _lock:
        b = _bozza_valida()
        if not b:
            return "Non c'è nessuna email in attesa."
        try:
            return _invia(b)
        except Exception as e:
            print("Segreteria, errore invio:", repr(e))
            return "L'email non è partita. Controlla il Terminale per i dettagli."


def scarta():
    with _lock:
        b = _bozza_valida()
        if not b:
            return "Non c'è nessuna email in attesa."
        elimina_bozza(b["id"])
        _stato["bozza"] = None
        _chiudi_approvazione(b, "Email annullata.")
        return "Email annullata."


def _nuova_email(testo):
    bozza = componi(testo)
    indirizzo = _trova_indirizzo(bozza.get("destinatario"))
    if not indirizzo:
        _stato["attesa_indirizzo"] = {"bozza": bozza, "richiesta": testo}
        chi = bozza.get("destinatario") or "questo destinatario"
        return f"Non ho l'indirizzo di {chi}. Dimmelo, oppure di' annulla."
    return _prepara(indirizzo, bozza, testo)

def _gestisci(testo):
    tl = testo.lower()
    parole = re.findall(r"\w+", tl)

    # Bozza troppo vecchia: la cancello
    b = _stato["bozza"]
    if b and time.time() - b["ora"] > SCADENZA_SECONDI:
        elimina_bozza(b["id"])
        _stato["bozza"] = b = None

    # Sto aspettando l'indirizzo email
    attesa = _stato["attesa_indirizzo"]
    if attesa:
        if "annulla" in parole:
            _stato["attesa_indirizzo"] = None
            return "Email annullata."
        indirizzo = _indirizzo_parlato(testo)
        if not indirizzo:
            return ("Non ho capito l'indirizzo. Ripetilo, ad esempio "
                    "mario chiocciola gmail punto com, oppure di' annulla.")
        _stato["attesa_indirizzo"] = None
        return _prepara(indirizzo, attesa["bozza"], attesa["richiesta"])

    # C'è una bozza in attesa di conferma
    if b:
        if NUOVA_EMAIL.search(testo):          # nuova richiesta: la vecchia bozza si scarta
            elimina_bozza(b["id"])
            _stato["bozza"] = None
            return _nuova_email(testo)
        if "invia" in parole and "non" not in parole:
            return _invia(b)
        if "annulla" in parole:
            elimina_bozza(b["id"])
            _stato["bozza"] = None
            _chiudi_approvazione(b, "Email annullata.")
            return "Email annullata."
        if MODIFICA.search(testo):
            elimina_bozza(b["id"])
            nuova = componi(b["richiesta"], b, testo)
            return _prepara(b["indirizzo"], nuova, b["richiesta"])
        return None   # altra domanda: la bozza resta in attesa, risponde Jarvis

    if NUOVA_EMAIL.search(testo):
        return _nuova_email(testo)
    return None

def gestisci(testo):
    testo = (testo or "").strip()
    if not testo:
        return None
    with _lock:
        try:
            return _gestisci(testo)
        except FileNotFoundError:
            return "Manca il file credentials.json nella cartella segreteria."
        except Exception as e:
            print("Segreteria, errore:", repr(e))
            return "La Segreteria ha avuto un problema. Controlla il Terminale per i dettagli."
