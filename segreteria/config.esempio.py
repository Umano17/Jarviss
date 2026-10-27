"""Impostazioni della Segreteria: copia questo file come config.py (che resta solo sul Mac, non va su GitHub).

    cp segreteria/config.esempio.py segreteria/config.py

Così com'è legge tutto dal file .env: la Segreteria parte anche senza Telegram e senza Gmail,
e le approvazioni compaiono solo sulla schermata. Per Gmail e Drive serve anche credentials.json (vedi LEGGIMI.txt).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or None
MODELLO = "claude-sonnet-5-5"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TUO_NOME = os.getenv("NOME_UTENTE", "")
RUBRICA = {}          # nomi brevi -> email, es. {"mario": "mario@example.com"}; meglio usare la Rubrica di Jarvis
