"""Zona sacra (Jarvis 3.7): i file che Jarvis può solo consigliare, mai modificare da solo.

Contiene: regole di sicurezza e approvazioni, accensione a distanza, Telegram (canale delle conferme),
email e messaggi a persone vere, pubblicazione, il guardiano degli aggiornamenti e questo stesso elenco.
Le chiavi (.env, segreteria/config.py, credenziali Google) non sono su GitHub e non passano mai dagli aggiornamenti.

Una modifica che tocca uno di questi file parte solo con il SÌ di Jonatan PIÙ il codice di verifica
di 6 cifre mandato su Telegram (vedi approvazioni.py). Questo file è a sua volta sacro.
"""
from __future__ import annotations

FILE_SACRI = (
    "zona_sacra.py",
    "approvazioni.py",
    "aggiornamenti.py",
    "avvio.py",
    "avvia_jarvis.command",
    "custode.py",                 # accensione a distanza, pagina iPhone con PIN (3.8)
    "installa_custode.command",
    "server.py",                  # contiene solo_da_questo_mac e il bind su 127.0.0.1
    "segreteria/telegram_bot.py",
    "segreteria/agente.py",       # conferma «invia» delle email
    "segreteria/email_gmail.py",
    "rubrica.py",                 # blocco non_contattare
    "pubblica.py",                # pubblicazione su internet
    ".gitignore",                 # tiene fuori da GitHub chiavi e dati
    "personalita_valori.md",      # valori fissi della personalità (fase 4)
)

# file che non devono MAI arrivare da un aggiornamento (se compaiono, l'aggiornamento è rifiutato)
MAI_DA_AGGIORNAMENTO = (".env", "segreteria/config.py", "segreteria/credentials.json",
                        "segreteria/token_segreteria.json", "credentials.json", "token_segreteria.json")


def e_sacro(percorso: str) -> bool:
    p = percorso.strip().removeprefix("./")
    return p in FILE_SACRI


def sacri_toccati(percorsi) -> list[str]:
    return sorted({p for p in percorsi if e_sacro(p)})


def vietati(percorsi) -> list[str]:
    return sorted({p for p in percorsi if p.strip().removeprefix("./") in MAI_DA_AGGIORNAMENTO})
