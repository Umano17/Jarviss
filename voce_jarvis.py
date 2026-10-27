"""Collegamento tra Jarvis e il motore vocale (cartella ~/JarvisVoce)."""
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:5055"
CARTELLA = Path.home() / "JarvisVoce"
_processo = None


def _post(percorso, dati, attesa=180):
    richiesta = urllib.request.Request(
        URL + percorso, data=json.dumps(dati).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(richiesta, timeout=attesa) as r:
        return r.read()


def motore_attivo():
    try:
        urllib.request.urlopen(URL + "/voci", timeout=1.5)
        return True
    except Exception:
        return False


def avvia_motore(attesa=60):
    """Accende il motore vocale se è spento. Va chiamata una volta all'avvio di Jarvis."""
    global _processo
    if motore_attivo():
        return True
    python = CARTELLA / ".venv" / "bin" / "python"
    server = CARTELLA / "server.py"
    if not python.exists() or not server.exists():
        print("Motore vocale non trovato in", CARTELLA)
        return False
    log = open(CARTELLA / "motore.log", "a")
    _processo = subprocess.Popen([str(python), str(server)], cwd=str(CARTELLA), stdout=log, stderr=log)
    for _ in range(attesa * 2):
        if motore_attivo():
            return True
        time.sleep(0.5)
    print("Il motore vocale non risponde: guarda ~/JarvisVoce/motore.log")
    return False


def parla(testo, attendi=False):
    """Fa parlare Jarvis con la voce impostata nella Libreria voci."""
    def _vai():
        try:
            _post("/dici", {"testo": testo})
        except Exception as e:
            print("Voce non disponibile:", e)
    if attendi:
        _vai()
    else:
        threading.Thread(target=_vai, daemon=True).start()


def zitto():
    """Interrompe la frase in corso."""
    try:
        _post("/stop", {}, attesa=5)
    except Exception:
        pass


def spegni_motore():
    """Spegne il motore se lo ha acceso Jarvis. Da chiamare alla chiusura."""
    if _processo and _processo.poll() is None:
        _processo.terminate()


if __name__ == "__main__":
    if avvia_motore():
        parla("Motore vocale collegato. Sono pronto.", attendi=True)
