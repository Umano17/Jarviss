"""Aggiornamenti di Jarvis da GitHub, con SÌ/NO su Telegram (Jarvis 3.7).

  /aggiorna  (Telegram)  → controlla se su GitHub c'è una versione nuova del ramo in uso, mostra cosa cambia e chiede SÌ/NO.
                           Se cambia un file della zona sacra (zona_sacra.py) dopo il SÌ serve anche il codice di verifica.
  /versione  (Telegram)  → versione, ramo e ultimo commit in uso.

Dopo il SÌ: avanzamento «fast-forward» (mai unioni automatiche), controllo che tutti i file Python si compilino,
poi riavvio tramite il guardiano (avvio.py). Se Jarvis non riparte sano entro 90 secondi il guardiano torna da solo
alla versione precedente e avvisa. I dati (cartella dati/, .env, configurazioni) non sono su GitHub e non vengono toccati.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import approvazioni
import zona_sacra

BASE = Path(__file__).parent
FILE_STATO = BASE / "dati" / "aggiornamento.json"
CODICE_RIAVVIO = 75          # il guardiano (avvio.py) riavvia Jarvis quando esce con questo codice


def _git(*args, timeout=60) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=BASE, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def leggi_stato() -> dict:
    try:
        d = json.loads(FILE_STATO.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def scrivi_stato(**campi) -> None:
    FILE_STATO.parent.mkdir(parents=True, exist_ok=True)
    d = leggi_stato()
    d.update(campi)
    tmp = FILE_STATO.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE_STATO)


def ramo() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD")[1]


def versione() -> str:
    import re
    m = re.search(r'^VERSIONE = "([^"]+)"', (BASE / "server.py").read_text(encoding="utf-8"), re.M)
    VERSIONE = m.group(1) if m else "?"
    _, riga = _git("log", "-1", "--format=%h · %cd · %s", "--date=format:%d/%m %H:%M")
    guardiano = "attivo" if os.getenv("JARVIS_GUARDIANO") == "1" else "spento (avvia con avvia_jarvis.command)"
    return f"Jarvis {VERSIONE}, ramo {ramo()}\nUltima modifica: {riga}\nGuardiano: {guardiano}"


def controlla() -> dict:
    """Cosa porterebbe un aggiornamento. Non cambia nulla."""
    r = ramo()
    cod, out = _git("fetch", "--quiet", "origin", r, timeout=90)
    if cod != 0:
        return {"ok": False, "messaggio": f"Non riesco a contattare GitHub: {out[:200]}"}
    remoto = f"origin/{r}"
    head = _git("rev-parse", "HEAD")[1]
    nuovo = _git("rev-parse", remoto)[1]
    if head == nuovo:
        return {"ok": True, "nuovo": False, "messaggio": f"Jarvis è già aggiornato (ramo {r})."}
    solo_qui = _git("rev-list", "--count", f"{remoto}..HEAD")[1]
    if solo_qui not in ("", "0"):
        return {"ok": False, "messaggio": f"Sul Mac ci sono {solo_qui} modifiche non ancora su GitHub: "
                                          "l'aggiornamento automatico è fermo per non perderle."}
    commit = _git("log", "--format=• %s", f"HEAD..{remoto}")[1].splitlines()
    file = [f for f in _git("diff", "--name-only", "HEAD", remoto)[1].splitlines() if f]
    return {"ok": True, "nuovo": True, "da": head, "a": nuovo, "ramo": r, "commit": commit, "file": file,
            "sacri": zona_sacra.sacri_toccati(file), "vietati": zona_sacra.vietati(file)}


def richiedi() -> str:
    """Chiamato da /aggiorna: prepara la richiesta di approvazione."""
    c = controlla()
    if not c.get("ok") or not c.get("nuovo"):
        return c["messaggio"]
    if c["vietati"]:
        return ("Aggiornamento RIFIUTATO: contiene file che non devono mai stare su GitHub (" +
                ", ".join(c["vietati"]) + "). Controlla il repository.")
    righe = [f"Aggiornare Jarvis (ramo {c['ramo']}) con {len(c['commit'])} modifiche?"]
    righe += c["commit"][:8] + (["• …"] if len(c["commit"]) > 8 else [])
    righe.append(f"File cambiati: {len(c['file'])}.")
    if c["sacri"]:
        righe.append("Tocca la ZONA SACRA: " + ", ".join(c["sacri"]) + ".")
    righe.append("Se Jarvis non riparte bene, torno da solo alla versione di adesso.")
    a = approvazioni.richiedi("aggiorna_jarvis", {"da": c["da"], "a": c["a"]}, "\n".join(righe),
                              chiave=f"aggiorna:{c['a']}", sacra=bool(c["sacri"]))
    return f"Ti ho chiesto conferma (richiesta n.{a['id']})."


def _compilano() -> tuple[bool, str]:
    file = [f for f in _git("ls-files", "*.py")[1].splitlines() if f]
    r = subprocess.run([sys.executable, "-m", "py_compile", *file], cwd=BASE, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout)[-400:]


def _esegui(da: str, a: str) -> str:
    """Dopo il SÌ (e il codice, se sacro): applica l'aggiornamento e fa ripartire Jarvis."""
    if _git("rev-parse", "HEAD")[1] != da:
        return "Nel frattempo Jarvis è cambiato: rifai /aggiorna."
    if _git("status", "--porcelain", "--untracked-files=no")[1]:
        return "Ci sono file modificati a mano sul Mac: aggiornamento fermo per non perderli."
    if zona_sacra.vietati(_git("diff", "--name-only", da, a)[1].splitlines()):
        return "Aggiornamento rifiutato: contiene file che non devono stare su GitHub."
    cod, out = _git("merge", "--ff-only", a)
    if cod != 0:
        return f"Aggiornamento non applicato: {out[:200]}"
    ok, errore = _compilano()
    if not ok:
        _git("reset", "--hard", da)
        return f"La nuova versione ha errori, sono rimasto sulla precedente. Dettaglio: {errore[:200]}"
    scrivi_stato(stato="in_prova", da=da, a=a, quando=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    try:
        import attivita
        attivita.registra(f"Aggiornamento applicato ({da[:7]} → {a[:7]}), riavvio in prova", "aggiornamenti", "ok")
    except Exception:
        pass
    if os.getenv("JARVIS_GUARDIANO") == "1":
        threading.Timer(3, lambda: os._exit(CODICE_RIAVVIO)).start()
        return "Aggiornamento applicato: riavvio Jarvis e ti avviso quando è pronto."
    return ("Aggiornamento applicato, ma il guardiano non è attivo: chiudi Jarvis e riaprilo con "
            "avvia_jarvis.command.")


def riavvia() -> str:
    if os.getenv("JARVIS_GUARDIANO") != "1":
        return "Il guardiano non è attivo: riavvia Jarvis con avvia_jarvis.command."
    threading.Timer(2, lambda: os._exit(CODICE_RIAVVIO)).start()
    return "Riavvio Jarvis…"


approvazioni.registra("aggiorna_jarvis", _esegui)


def comando_telegram(testo: str) -> str | None:
    """/aggiorna, /versione, /riavvia. None se il testo non è uno di questi comandi."""
    t = (testo or "").strip().lower().split("@")[0]
    if t == "/aggiorna":
        return richiedi()
    if t == "/versione":
        return versione()
    if t == "/riavvia":
        return riavvia()
    return None


if __name__ == "__main__":
    print(versione())
    print(json.dumps(controlla(), ensure_ascii=False, indent=1))
