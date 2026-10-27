"""Fuso orario di Jonatan (Jarvis 3.7).

Si sceglie nelle Impostazioni (la schermata propone quello del browser). Lo usano: ora detta da Jarvis, briefing,
riepilogo settimanale, notizie del giorno e gli eventi creati in agenda. Senza fuso impostato vale l'ora del Mac,
come prima.
"""
from __future__ import annotations

import datetime as dt

try:
    from zoneinfo import ZoneInfo
except ImportError:          # Python molto vecchio: si resta sull'ora del Mac
    ZoneInfo = None


def valido(nome: str) -> bool:
    if not ZoneInfo or not isinstance(nome, str) or not (2 < len(nome) < 60) or "/" not in nome:
        return False
    try:
        ZoneInfo(nome)
        return True
    except Exception:
        return False


def nome_fuso() -> str:
    """Il fuso scelto nelle Impostazioni, oppure "" (= ora del Mac)."""
    try:
        import impostazioni
        f = impostazioni.carica().get("fuso", "")
        return f if valido(f) else ""
    except Exception:
        return ""


def adesso() -> dt.datetime:
    """Ora attuale nel fuso di Jonatan (senza fuso impostato: ora del Mac). Restituisce un orario «semplice»."""
    f = nome_fuso()
    if f:
        return dt.datetime.now(ZoneInfo(f)).replace(tzinfo=None)
    return dt.datetime.now()


def oggi() -> dt.date:
    return adesso().date()


def descrizione() -> str:
    return nome_fuso().replace("_", " ") or "quello del Mac"


def al_mac(d: dt.datetime) -> dt.datetime:
    """Un orario detto da Jonatan (nel suo fuso) convertito nell'ora del Mac, per l'app Calendario."""
    f = nome_fuso()
    if not f or d.tzinfo is not None:
        return d.astimezone().replace(tzinfo=None) if d.tzinfo is not None else d
    return d.replace(tzinfo=ZoneInfo(f)).astimezone().replace(tzinfo=None)
