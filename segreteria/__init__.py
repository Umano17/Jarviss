"""Segreteria di Jarvis: email Gmail con conferma, archivio Drive, Telegram."""
from .agente import gestisci, bozza_in_attesa, approva, scarta
from .telegram_bot import avvia_telegram, notifica, configurato

__all__ = ["gestisci", "bozza_in_attesa", "approva", "scarta", "avvia_telegram", "notifica", "configurato"]
