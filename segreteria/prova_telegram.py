"""Prova del bot Telegram senza Jarvis.
Avvio: cd ~/jarvis  poi  python3 -m segreteria.prova_telegram   (Ctrl + C per fermare)
"""
import time
from .telegram_bot import avvia_telegram

def eco(testo):
    return f"(Prova) Jarvis non è ancora collegato. Hai scritto: {testo}"

avvia_telegram(eco)
print("Scrivi al bot dal cellulare. Ctrl + C per fermare.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Fermato.")
