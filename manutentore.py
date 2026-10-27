"""Il Manutentore di Jarvis: netturbino e architetto, sempre al lavoro mentre Jarvis è acceso.

Ogni ora (gratis, senza modello):
  - CONTROLLI: tutti i moduli si compilano, gli strumenti di Jarvis sono collegati (TOOLS ↔ esegui ↔ etichette ↔
    squadre), le squadre citate nel codice esistono, i file di dati sono leggibili, le skill sono valide,
    il file .env ha le chiavi, le richieste di approvazione non sono bloccate.
  - PULIZIA SICURA (automatica, niente si perde): archivia i registri troppo lunghi (uso.jsonl),
    sposta nell'archivio gli zip di pubblicazione vecchi, svuota le cache __pycache__ orfane.
Ogni lunedì (con il modello, pochi centesimi): l'ARCHITETTO legge la mappa del codice e il rapporto e propone
  i 3 miglioramenti più utili (ponti tra moduli, doppioni, incongruenze).

Quello che il Manutentore NON fa da solo: modificare il codice di Jarvis. Le correzioni al codice
restano proposte: passano da Jonatan (o da una sessione di sviluppo) per evitare che un errore automatico rompa
Jarvis di notte. Le pulizie che toccano dati veri chiedono SÌ/NO su Telegram.

Prova dal Terminale:  python manutentore.py            (controlli + rapporto, senza pulire)
                      python manutentore.py --pulisci  (anche la pulizia sicura)
"""
from __future__ import annotations

import ast
import datetime as dt
import gzip
import json
import os
import py_compile
import re
import shutil
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).parent
DATI = BASE / "dati"
RAPPORTI = DATI / "manutenzione"
ARCHIVIO = DATI / "archivio"
ESCLUSE = {"venv", "_archivio", "backup", "__pycache__", ".git", "demo", "progetti", "dati", "_scambio", "Claude outputs"}

_stato = {"ultimo": None, "in_corso": False}
_lock = threading.Lock()


# ================================================================= CONTROLLI

def _py() -> list[Path]:
    return sorted(p for p in BASE.rglob("*.py") if not (set(p.relative_to(BASE).parts[:-1]) & ESCLUSE))


def controlla_compilazione() -> list[dict]:
    out = []
    for f in _py():
        try:
            py_compile.compile(str(f), doraise=True, cfile=os.devnull if os.name != "nt" else None)
        except py_compile.PyCompileError as e:
            out.append({"livello": "errore", "area": "codice", "testo": f"{f.name} non si compila: {str(e.msg)[:160]}"})
        except Exception:
            pass
    return out


def _sorgente(nome: str) -> str:
    try:
        return (BASE / nome).read_text(encoding="utf-8")
    except OSError:
        return ""


def _nomi_tools(src: str) -> list[str]:
    """Nomi degli strumenti dichiarati in TOOLS (letti dal testo, senza importare cervello)."""
    i = src.find("TOOLS = [")
    if i < 0:
        return []
    fine = src.find("\n]\n", i)
    return re.findall(r'"name":\s*"([a-z0-9_]+)"', src[i:fine])


def controlla_strumenti() -> list[dict]:
    """Ogni strumento deve avere: ramo in esegui_tool, etichetta per la schermata, squadra per la Sala controllo."""
    out = []
    src = _sorgente("cervello.py")
    sq = _sorgente("squadre.py")
    nomi = _nomi_tools(src)
    if not nomi:
        return [{"livello": "errore", "area": "strumenti", "testo": "Non trovo la lista TOOLS in cervello.py."}]
    doppi = sorted({n for n in nomi if nomi.count(n) > 1})
    if doppi:
        out.append({"livello": "errore", "area": "strumenti", "testo": "Strumenti dichiarati due volte: " + ", ".join(doppi)})
    m = re.search(r"STRUMENTI_PRODUTTIVITA\s*=\s*\{(.*?)\}", src, re.S)
    prod = set(re.findall(r'"([a-z0-9_]+)"', m.group(1))) if m else set()
    et = src[src.find("ETICHETTE = {"):]
    et = et[:et.find("\n}\n")]
    senza_ramo, senza_et, senza_sq = [], [], []
    for n in nomi:
        if f'nome == "{n}"' not in src and n not in prod:
            senza_ramo.append(n)
        if f'"{n}":' not in et:
            senza_et.append(n)
        if f'"{n}":' not in sq:
            senza_sq.append(n)
    if senza_ramo:
        out.append({"livello": "errore", "area": "strumenti", "testo": "Strumenti senza esecuzione (Jarvis risponderebbe «strumento sconosciuto»): " + ", ".join(senza_ramo)})
    if senza_et:
        out.append({"livello": "avviso", "area": "strumenti", "testo": "Strumenti senza frase di attesa sullo schermo: " + ", ".join(senza_et)})
    if senza_sq:
        out.append({"livello": "info", "area": "squadre", "testo": "Strumenti non assegnati a una squadra (non compaiono nella Sala controllo): " + ", ".join(senza_sq)})
    return out


def controlla_squadre() -> list[dict]:
    """Le squadre e gli operatori usati nel codice devono esistere nei file squadre/*.md."""
    out = []
    try:
        sys.path.insert(0, str(BASE))
        import squadre
        squadre.carica()
        st = {s["id"]: {o["id"] for o in s["operatori"]} for s in squadre.stato()["squadre"]}
    except Exception as e:
        return [{"livello": "errore", "area": "squadre", "testo": f"Le squadre non si caricano: {e}"}]
    usati = set()
    for f in _py():
        for sq, op in re.findall(r'turno\("([a-z0-9-]+)",\s*"([a-z0-9-]+)"', f.read_text(encoding="utf-8")):
            usati.add((sq, op, f.name))
    src = _sorgente("squadre.py")
    for sq, op in re.findall(r'\("([a-z0-9-]+)",\s*"([a-z0-9-]+)"\)', src[src.find("STRUMENTI = {"):src.find("\n}\n", src.find("STRUMENTI = {"))]):
        usati.add((sq, op, "squadre.py"))
    mancanti = sorted({f"{sq}/{op} ({f})" for sq, op, f in usati if sq not in st or (op != "responsabile" and op not in st[sq])})
    if mancanti:
        out.append({"livello": "avviso", "area": "squadre", "testo": "Operatori citati nel codice ma assenti in squadre/*.md: " + ", ".join(mancanti)})
    return out


def controlla_dati() -> list[dict]:
    out = []
    for f in list(BASE.glob("*.json")) + list(DATI.glob("*.json")):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            out.append({"livello": "errore", "area": "dati", "testo": f"{f.relative_to(BASE)} è illeggibile ({str(e)[:80]}): c'è una copia in backup?"})
    for f in list(BASE.glob("*.tmp")) + list(DATI.glob("*.tmp")):
        if time.time() - f.stat().st_mtime > 3600:
            out.append({"livello": "info", "area": "dati", "testo": f"File temporaneo rimasto da un salvataggio interrotto: {f.relative_to(BASE)}"})
    return out


def controlla_skill() -> list[dict]:
    out = []
    for f in sorted((BASE / "skills").glob("*/SKILL.md")):
        t = f.read_text(encoding="utf-8")
        if not t.startswith("---") or not re.search(r"^name:\s*\S+", t, re.M) or not re.search(r"^description:\s*\S+", t, re.M):
            out.append({"livello": "avviso", "area": "skill", "testo": f"Skill {f.parent.name}: intestazione incompleta (name/description)."})
        elif re.search(r"^name:\s*(\S+)", t, re.M).group(1) != f.parent.name:
            out.append({"livello": "avviso", "area": "skill", "testo": f"Skill {f.parent.name}: il campo name non coincide con la cartella."})
    return out


def controlla_env() -> list[dict]:
    out = []
    try:
        env = (BASE / ".env").read_text(encoding="utf-8")
    except OSError:
        return [{"livello": "errore", "area": "configurazione", "testo": "Manca il file .env."}]
    chiavi = dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", env, re.M))
    if not chiavi.get("ANTHROPIC_API_KEY", "").strip():
        out.append({"livello": "errore", "area": "configurazione", "testo": "ANTHROPIC_API_KEY vuota nel file .env: Jarvis non può pensare."})
    if not chiavi.get("TELEGRAM_TOKEN") or not chiavi.get("TELEGRAM_CHAT_ID"):
        out.append({"livello": "avviso", "area": "configurazione", "testo": "Telegram non configurato: le richieste di approvazione arrivano solo sullo schermo."})
    return out


def controlla_approvazioni() -> list[dict]:
    try:
        import approvazioni
        l = approvazioni.in_attesa()
    except Exception:
        return []
    vecchie = [a for a in l if a["scade_tra_min"] < 60]
    if vecchie:
        return [{"livello": "info", "area": "approvazioni", "testo": f"{len(vecchie)} richieste di approvazione scadono entro un'ora senza risposta."}]
    return []


def controlla_versioni() -> list[dict]:
    """Numeri di versione rimasti indietro nei testi (piccole incongruenze)."""
    m = re.search(r'VERSIONE\s*=\s*"([\d.]+)"', _sorgente("server.py"))
    if not m:
        return []
    v = m.group(1)
    vecchi = []
    for f in _py():
        prima = f.read_text(encoding="utf-8").splitlines()[:3]
        for r in prima:
            mm = re.search(r"(?:Jarvis|versione)\s+(\d\.\d+)", r)
            if mm and mm.group(1) != v and float(mm.group(1)) < float(v):
                vecchi.append(f"{f.name} ({mm.group(1)})")
    if vecchi:
        return [{"livello": "info", "area": "codice", "testo": f"Intestazioni con versione vecchia (attuale {v}): " + ", ".join(sorted(set(vecchi)))}]
    return []


CONTROLLI = [controlla_compilazione, controlla_strumenti, controlla_squadre, controlla_dati, controlla_skill,
             controlla_env, controlla_approvazioni, controlla_versioni]


# ================================================================= PULIZIA SICURA (niente si cancella: si archivia)

def _archivia_righe(f: Path, tieni: int, nome_archivio: str) -> str | None:
    if not f.exists():
        return None
    righe = f.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    if len(righe) <= tieni * 1.5:
        return None
    vecchie, nuove = righe[:-tieni], righe[-tieni:]
    ARCHIVIO.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVIO / f"{nome_archivio}-{dt.date.today().isoformat()}.gz"
    with gzip.open(dest, "at", encoding="utf-8") as g:
        g.writelines(vecchie)
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_text("".join(nuove), encoding="utf-8")
    os.replace(tmp, f)
    return f"{f.name}: {len(vecchie)} righe vecchie archiviate in {dest.relative_to(BASE)}"


def pulizia() -> list[str]:
    fatto = []
    for f, tieni, nome in [(BASE / "uso.jsonl", 40000, "uso")]:
        try:
            r = _archivia_righe(f, tieni, nome)
            if r:
                fatto.append(r)
        except Exception as e:
            fatto.append(f"{f.name}: archiviazione non riuscita ({e})")
    # zip di pubblicazione vecchi di 14 giorni → archivio (si possono rifare quando serve)
    for z in (BASE / "demo").glob("*/pubblica-*.zip"):
        if time.time() - z.stat().st_mtime > 14 * 86400:
            dest = ARCHIVIO / "zip-demo" / z.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(z), str(dest))
            fatto.append(f"Zip vecchio spostato in archivio: {z.name}")
    # cache Python di moduli che non esistono più
    for c in BASE.rglob("__pycache__/*.pyc"):
        if set(c.relative_to(BASE).parts) & {"venv", ".git", "_archivio"}:
            continue
        sorgente = c.parent.parent / (c.name.split(".")[0] + ".py")
        if not sorgente.exists():
            try:
                c.unlink()
                fatto.append(f"Cache orfana tolta: {c.relative_to(BASE)}")
            except OSError:
                pass
    return fatto


# ================================================================= ARCHITETTO (settimanale, con il modello)

def mappa_codice() -> str:
    """Mappa compatta: per ogni modulo righe, funzioni pubbliche e chi importa chi."""
    righe = []
    for f in _py():
        if f.name.startswith("prova"):
            continue
        src = f.read_text(encoding="utf-8")
        try:
            albero = ast.parse(src)
        except SyntaxError:
            continue
        funz = [n.name for n in albero.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        imp = sorted({(n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
                      for n in ast.walk(albero) if isinstance(n, (ast.Import, ast.ImportFrom))
                      for a in (n.names if isinstance(n, ast.Import) else [n]) if (n.module if isinstance(n, ast.ImportFrom) else a.name)})
        locali = [m for m in imp if (BASE / f"{m}.py").exists() or (BASE / m).is_dir() and m not in ESCLUSE]
        righe.append(f"{f.relative_to(BASE)} ({len(src.splitlines())} righe) usa {', '.join(locali) or '-'} | funzioni: {', '.join(funz[:25])}")
    return "\n".join(righe)


SYSTEM_ARCHITETTO = """Sei l'Architetto della squadra Manutenzione di Jarvis (assistente personale in Python, Flask, un solo file
HTML per l'interfaccia). Ricevi la mappa dei moduli e l'ultimo rapporto dei controlli automatici.
Proponi i 3 interventi più utili per: collegare meglio i moduli (ponti), togliere doppioni e contrasti, rendere più
veloci i processi, ridurre i costi. Per ognuno: cosa, perché, file coinvolti, rischio (basso/medio/alto), quanto lavoro.
Non proporre riscritture totali né nuove dipendenze pesanti. Non toccare le regole di sicurezza (conferme SÌ/NO,
server solo locale). Scrivi in italiano semplice, massimo 350 parole."""


def revisione_architetto(rapporto: dict) -> str:
    import cervello
    testo = ("MAPPA DEI MODULI\n" + mappa_codice() + "\n\nULTIMO RAPPORTO\n" +
             "\n".join(f"- [{p['livello']}] {p['area']}: {p['testo']}" for p in rapporto["problemi"]) or "- nessun problema")
    r = cervello.crea("jarvis", model=cervello.MODEL, max_tokens=1500, system=SYSTEM_ARCHITETTO,
                      messages=[{"role": "user", "content": testo}])
    proposta = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    RAPPORTI.mkdir(parents=True, exist_ok=True)
    (RAPPORTI / f"architetto-{dt.date.today().isoformat()}.md").write_text(
        f"# Proposte dell'Architetto – {dt.date.today().strftime('%d/%m/%Y')}\n\n{proposta}\n", encoding="utf-8")
    return proposta


# ================================================================= GIRO COMPLETO

def giro(pulisci: bool = True) -> dict:
    with _lock:
        if _stato["in_corso"]:
            return _stato["ultimo"] or {}
        _stato["in_corso"] = True
    inizio = time.time()
    problemi = []
    try:
        for c in CONTROLLI:
            try:
                problemi += c()
            except Exception as e:
                problemi.append({"livello": "avviso", "area": "manutentore", "testo": f"Il controllo {c.__name__} non è riuscito: {e}"})
        pulizie = pulizia() if pulisci else []
        r = {"ora": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "durata_s": round(time.time() - inizio, 1),
             "problemi": problemi, "pulizie": pulizie,
             "errori": sum(1 for p in problemi if p["livello"] == "errore"),
             "avvisi": sum(1 for p in problemi if p["livello"] == "avviso")}
        RAPPORTI.mkdir(parents=True, exist_ok=True)
        (RAPPORTI / "ultimo.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        _stato["ultimo"] = r
        try:
            import attivita
            testo = (f"Controllo: {r['errori']} errori, {r['avvisi']} avvisi" +
                     (f", pulizie: {len(pulizie)}" if pulizie else ""))
            attivita.registra(testo, "manutenzione", "errore" if r["errori"] else "avviso" if r["avvisi"] else "ok")
        except Exception:
            pass
        return r
    finally:
        _stato["in_corso"] = False


def ultimo() -> dict | None:
    if _stato["ultimo"]:
        return _stato["ultimo"]
    try:
        return json.loads((RAPPORTI / "ultimo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def testo_rapporto(r: dict) -> str:
    if not r:
        return "Nessun controllo ancora fatto."
    t = [f"Manutenzione {r['ora']}: {r['errori']} errori, {r['avvisi']} avvisi."]
    t += [f"- [{p['livello']}] {p['testo']}" for p in r["problemi"] if p["livello"] != "info"]
    if r["pulizie"]:
        t.append("Pulizia: " + "; ".join(r["pulizie"][:5]))
    return "\n".join(t)


def _notifica(testo: str) -> None:
    try:
        from segreteria import notifica
        notifica(testo)
    except Exception:
        pass


def _ciclo() -> None:
    time.sleep(90)                                   # lascia partire Jarvis
    ultimo_avviso, ultima_revisione = "", ""
    while True:
        try:
            import squadre
            with squadre.turno("manutenzione", "ispettore", "Giro di controllo"):
                r = giro(pulisci=True)
            gravi = [p["testo"] for p in r["problemi"] if p["livello"] == "errore"]
            firma = "|".join(sorted(gravi))
            if gravi and firma != ultimo_avviso:     # avvisa solo quando cambia qualcosa, non ogni ora
                _notifica("🛠 Manutentore: " + testo_rapporto(r))
            ultimo_avviso = firma
            oggi = dt.date.today()
            if oggi.weekday() == 0 and ultima_revisione != oggi.isoformat() and \
                    os.getenv("MANUTENZIONE_ARCHITETTO", "si").lower() not in ("no", "0", "off"):
                ultima_revisione = oggi.isoformat()
                with squadre.turno("manutenzione", "architetto", "Revisione settimanale del codice"):
                    proposta = revisione_architetto(r)
                _notifica("🏗 Architetto – proposte della settimana (nessuna modifica fatta da solo):\n\n" + proposta[:3500])
        except Exception as e:
            print("Manutentore:", repr(e))
        time.sleep(3600)


_avviato = False


def avvia() -> None:
    global _avviato
    if not _avviato:
        _avviato = True
        threading.Thread(target=_ciclo, daemon=True).start()


if __name__ == "__main__":
    print(testo_rapporto(giro(pulisci="--pulisci" in sys.argv)))
