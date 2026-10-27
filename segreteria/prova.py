"""Prova della Segreteria nel Terminale, senza toccare Jarvis.
Avvio: cd ~/jarvis  poi  python3 -m segreteria.prova
"""
from .agente import gestisci
from .telegram_bot import notifica

print("Prova Segreteria. Scrivi come parleresti a Jarvis. 'esci' per uscire.")
notifica("Prova: la Segreteria riesce a scriverti su Telegram.")
while True:
    t = input("\nTu: ")
    if t.strip().lower() == "esci":
        break
    r = gestisci(t)
    print("Segreteria:", r if r is not None else "(non riguarda le email: risponderebbe Jarvis)")
