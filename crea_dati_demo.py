"""Dati demo: riempie dati/ con attività, clienti, preventivi e note inventati, per mostrare Jarvis senza dati veri.

Uso, in una copia a parte di Jarvis (mai nella cartella di tutti i giorni):
    git clone ... ~/jarvis-demo  (oppure copia la cartella senza dati/)
    cd ~/jarvis-demo && python crea_dati_demo.py

Usa le funzioni vere di Jarvis (Lead, Produttività, Memoria): al posto di OpenStreetMap c'è una risposta finta,
quindi non serve internet. Se dati/ contiene già qualcosa lo script si ferma: i dati veri non si toccano mai.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import lead_maps
import memoria
import produttivita as prod

DATI = Path(__file__).parent / "dati"

# attività inventate: nomi, indirizzi e telefoni non corrispondono a persone o aziende reali
ATTIVITA = [
    ("1", "Pizzeria Luna", "0421 000101", ""),
    ("2", "Trattoria Al Pozzo", "0421 000102", ""),
    ("3", "Osteria del Faro", "0421 000103", "https://osteriadelfaro.example"),
    ("4", "Ristorante La Conchiglia", "0421 000104", ""),
    ("5", "Da Nino al Porto", "0421 000105", ""),
    ("6", "Bistrot Ventoso", "", ""),
]

NOTE = [
    ("Chi sono", "Realizzo siti web per attività locali: demo gratuita, poi sito su misura con manutenzione.",
     "business"),
    ("Tono dei messaggi", "Frasi brevi, del lei ai titolari, niente parole inglesi se c'è quella italiana.", "stile"),
    ("Prima di contattare", "Mai contattare un'attività senza aver controllato che non abbia già un sito.",
     "istruzione"),
]


class _Risposta:
    def __init__(self, dati):
        self.dati, self.status_code = dati, 200

    def json(self):
        return self.dati


class _MappaFinta:
    """Sostituisce Overpass: restituisce sempre le attività inventate qui sopra."""
    def post(self, url, data=None, headers=None, timeout=None):
        elementi = []
        for id_, nome, telefono, sito in ATTIVITA:
            t = {"name": nome, "addr:street": "Via Esempio", "addr:housenumber": id_, "addr:city": "Jesolo"}
            if telefono:
                t["phone"] = telefono
            if sito:
                t["website"] = sito
            elementi.append({"type": "node", "id": int(id_), "tags": t})
        return _Risposta({"elements": elementi})


def _verifica_finta(gruppo):
    """Sostituisce la ricerca web: l'ultima attività del gruppo resta «da verificare»."""
    return [{"n": i, "esito": "dubbio" if i == len(gruppo) else "senza", "url": ""} for i in range(1, len(gruppo) + 1)]


def dati_presenti() -> bool:
    return DATI.exists() and any(DATI.iterdir())


def crea() -> str:
    if dati_presenti():
        raise SystemExit(f"In {DATI} ci sono già dei dati: non faccio niente. Usa una copia di Jarvis senza dati/.")
    os.environ.pop("GOOGLE_PLACES_API_KEY", None)        # la demo usa sempre la mappa finta

    ris = lead_maps.cerca("ristoranti", "Jesolo", sito="senza", clienti_esistenti=[], http=_MappaFinta(),
                          verificatore=_verifica_finta)
    if "errore" in ris:
        raise SystemExit(ris["errore"])
    lead_maps.salva(ris, su_drive=False, nei_clienti=True)

    # un percorso credibile nella pipeline: demo pronta, contattato, cliente con preventivo e incasso
    clienti = {c["nome"]: c for c in prod.clienti()}
    prod.aggiorna_cliente(clienti["Pizzeria Luna"]["id"], stato="demo", nota="Demo ★★★ pronta.")
    prod.aggiorna_cliente(clienti["Trattoria Al Pozzo"]["id"], stato="contattato", nota="Mandato il messaggio.")
    nino = clienti["Da Nino al Porto"]["id"]
    prod.aggiorna_cliente(nino, stato="cliente", nota="Ha accettato il sito ★★★★.")
    preventivo, errore = prod.crea_preventivo(nino, ["sito-4"], note="Consegna in due settimane.")
    if errore:
        raise SystemExit(errore)
    prod.aggiorna_preventivo(preventivo["id"], stato="accettato")
    prod.registra_incasso(nino, 345, "Acconto sito ★★★★ (50%)")

    for titolo, testo, categoria in NOTE:
        memoria.salva(titolo, testo, categoria)

    return (f"Dati demo pronti in {DATI}: {len(ris['righe'])} lead, {len(prod.clienti())} clienti, "
            f"1 preventivo, 1 incasso, {len(NOTE)} note.")


if __name__ == "__main__":
    try:
        print(crea())
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(1)
