"""Diario delle attività automatiche di Jarvis (3.8): cosa ha fatto da solo e quando.

Una riga per evento in dati/attivita.jsonl: {"t": secondi, "fonte": "...", "testo": "...", "tipo": "ok|info|avviso|errore"}.
Lo scrivono approvazioni, aggiornamenti, AI di riserva, Manutentore, briefing, post Instagram, compiti dal telefono
e il custode (accensione/spegnimento a distanza). Lo legge il pannello dell'iPhone.
Il file si accorcia da solo (ultime 3000 righe). Non deve mai far fallire il lavoro.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

FILE = Path(__file__).parent / "dati" / "attivita.jsonl"
MAX_RIGHE = 3000
_lock = threading.Lock()


def registra(testo: str, fonte: str = "jarvis", tipo: str = "info") -> None:
    try:
        riga = json.dumps({"t": int(time.time()), "fonte": str(fonte)[:30], "testo": str(testo)[:240],
                           "tipo": tipo if tipo in ("ok", "info", "avviso", "errore") else "info"}, ensure_ascii=False)
        with _lock:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FILE, "a", encoding="utf-8") as f:
                f.write(riga + "\n")
            if FILE.stat().st_size > 600_000:          # circa 3000 righe: tiene le più recenti
                righe = FILE.read_text(encoding="utf-8").splitlines()[-MAX_RIGHE // 2:]
                tmp = FILE.with_suffix(".tmp")
                tmp.write_text("\n".join(righe) + "\n", encoding="utf-8")
                os.replace(tmp, FILE)
    except Exception as e:
        print("Attività: non riesco a scrivere:", repr(e)[:120])


def recenti(n: int = 40, da: float = 0) -> list[dict]:
    try:
        with _lock:
            righe = FILE.read_text(encoding="utf-8").splitlines()[-max(n * 3, 200):]
    except OSError:
        return []
    out = []
    for r in reversed(righe):
        try:
            x = json.loads(r)
        except ValueError:
            continue
        if x.get("t", 0) >= da:
            out.append(x)
        if len(out) >= n:
            break
    return out
