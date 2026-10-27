"""Bozze e invio email dal Gmail della Segreteria."""
import base64
from email.mime.text import MIMEText
from .config import TUO_NOME
from .google_account import servizio
from .modello import chiedi_json

def _gmail():
    return servizio("gmail", "v1")

def crea_bozza(a, oggetto, testo):
    msg = MIMEText(testo, "plain", "utf-8")
    msg["to"] = a
    msg["subject"] = oggetto
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return _gmail().users().drafts().create(
        userId="me", body={"message": {"raw": raw}}).execute()["id"]

def invia_bozza(id_bozza):
    _gmail().users().drafts().send(userId="me", body={"id": id_bozza}).execute()

def elimina_bozza(id_bozza):
    try:
        _gmail().users().drafts().delete(userId="me", id=id_bozza).execute()
    except Exception:
        pass  # bozza già cancellata a mano: va bene così

ISTR_EMAIL = f"""Scrivi un'email in italiano per conto di {TUO_NOME}: chiara, cortese e professionale.
Firma: "Segreteria di {TUO_NOME}".
Restituisci JSON: {{"destinatario": "nome o indirizzo come detto dall'utente",
 "oggetto": "...", "testo": "..."}}"""

def componi(richiesta, bozza=None, modifica=None):
    if bozza:
        testo = (f"Richiesta originale: {richiesta}\n\nBozza attuale:\n"
                 f"Oggetto: {bozza['oggetto']}\n{bozza['testo']}\n\n"
                 f"Modifica richiesta: {modifica}")
    else:
        testo = richiesta
    return chiedi_json(ISTR_EMAIL, testo)
