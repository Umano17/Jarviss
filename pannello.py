"""Pannello per l'iPhone (Jarvis 3.8): dati per la pagina di controllo e compiti alle squadre.

La pagina la mostra il custode (custode.py), che chiede questi dati a Jarvis in locale:
  GET  /api/pannello          stato generale, flusso cervello → squadre, cronologia, rapporto
  POST /api/pannello/compito  {"squadra": "contenuti", "testo": "..."}: il compito passa dal cervello come un messaggio
                              di Jonatan; il risultato arriva su Telegram e nel diario. Le azioni critiche chiedono
                              comunque il SÌ (approvazioni).
Solo lettura, tranne i compiti. Nessun dato personale (clienti, email) esce dal Mac oltre a quanto mostrato.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import attivita

BASE = Path(__file__).parent
AVVIATO = time.time()
ICONE = {"agenda": "📅", "amministrazione": "🧾", "commerciale": "🤝", "contenuti": "✍️",
         "manutenzione": "🔧", "notizie": "📰", "progetti": "📁", "ricerca": "🔎", "seo": "📍", "siti": "🌐",
         "support": "🛟", "testi": "📝", "lead": "🧲"}
MAX_NODI = 5
_compiti: list[dict] = []
_lock = threading.Lock()


def _durata(sec: float) -> str:
    sec = int(sec)
    g, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    return f"{g} g {h} h" if g else f"{h} h {m} min" if h else f"{m} min"


_disco = {"t": 0.0, "v": None}

# Spazio libero come lo conta macOS (Impostazioni > Spazio): include lo spazio «eliminabile» (istantanee locali,
# cache di iCloud) che il Mac libera da solo. shutil.disk_usage non lo conta e segnava il disco quasi pieno.
_JS_DISCO = ("ObjC.import('Foundation');var u=$.NSURL.fileURLWithPath('/');"
             "var k=[$.NSURLVolumeAvailableCapacityForImportantUsageKey,$.NSURLVolumeTotalCapacityKey];"
             "var r=u.resourceValuesForKeysError(k,null);"
             "ObjC.unwrap(r.objectForKey(k[0]))+' '+ObjC.unwrap(r.objectForKey(k[1]))")


def _disco_percento():
    if _disco["v"] is not None and time.time() - _disco["t"] < 600:
        return _disco["v"]
    v = None
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["osascript", "-l", "JavaScript", "-e", _JS_DISCO],
                               capture_output=True, text=True, timeout=10)
            libero, totale = (float(x) for x in r.stdout.split()[:2])
            if totale > 0:
                v = round((totale - libero) / totale * 100)
        except (OSError, ValueError, subprocess.SubprocessError):
            v = None
    if v is None:
        try:
            d = shutil.disk_usage(str(BASE))
            v = round(d.used / d.total * 100)
        except OSError:
            return None
    _disco.update(t=time.time(), v=v)
    return v


def _mac() -> dict:
    out = {}
    disco = _disco_percento()
    if disco is not None:
        out["disco"] = disco
    try:
        out["carico"] = round(os.getloadavg()[0], 1)
    except (OSError, AttributeError):
        pass
    return out


def _agenti() -> tuple[list[dict], list[dict]]:
    """(nodi del grafico, elenco completo) dalle squadre: sforzo = stress calcolato dalla squadra Support."""
    import squadre
    st = squadre.stato()
    ora = st["adesso"]
    tutte = []
    for s in st["squadre"]:
        al_lavoro = [o for o in s["operatori"] if o["stato"] == "occupato"]
        ultimo = max((e["t"] for e in st["registro"] if e["squadra"] == s["id"]), default=0)
        cosa = "; ".join(f"{o['nome']}: {o['attivita'] or 'al lavoro'}" for o in al_lavoro[:2])
        tutte.append({"id": s["id"], "nome": s["nome"], "icona": ICONE.get(s["id"], "•"), "sforzo": s["stress"],
                      "coda": s["coda"], "errori": s["errori_recenti"], "attivo": bool(al_lavoro),
                      "cosa": cosa or ("in coda: %d" % s["coda"] if s["coda"] else "fermo"),
                      "ultimo_min": int((ora - ultimo) / 60) if ultimo else None})
    # nel grafico: prima chi lavora, poi chi ha lavorato da poco, poi il resto (max 5)
    ordine = sorted(tutte, key=lambda a: (not a["attivo"], -a["sforzo"],
                                          a["ultimo_min"] if a["ultimo_min"] is not None else 10 ** 6))
    return ordine[:MAX_NODI], ordine


def dati() -> dict:
    import uso
    out = {"versione": "", "acceso_da": _durata(time.time() - AVVIATO), "mac": _mac(), "adesso": time.time()}
    try:
        import ai
        out["ai"] = ai.stato()
    except Exception:
        out["ai"] = {}
    try:
        import approvazioni
        out["approvazioni_in_attesa"] = len(approvazioni.in_attesa())
    except Exception:
        out["approvazioni_in_attesa"] = 0
    try:
        nodi, tutte = _agenti()
    except Exception as e:
        nodi, tutte = [], []
        print("Pannello, squadre:", repr(e))
    out["nodi"], out["squadre"] = nodi, tutte
    out["cronologia"] = attivita.recenti(25)
    oggi, sett = uso.riepilogo(1), uso.riepilogo(7)
    out["rapporto"] = {"oggi_richieste": oggi["totale"]["richieste"], "oggi_costo": oggi["totale"]["costo"],
                       "sett_richieste": sett["totale"]["richieste"], "sett_costo": sett["totale"]["costo"],
                       "valuta": oggi.get("valuta", "€"),
                       "sett_fatti": len(attivita.recenti(500, time.time() - 7 * 86400))}
    with _lock:
        out["compiti"] = [{k: c[k] for k in ("id", "squadra", "testo", "stato", "creato")} for c in _compiti[-8:]][::-1]
    return out


# ---------------------------------------------------------------- compiti dal telefono

def _esegui_compito(c: dict) -> None:
    import cervello
    c["stato"] = "in corso"
    attivita.registra(f"Compito dal telefono a {c['squadra']}: {c['testo'][:120]}", "telefono", "info")
    richiesta = (f"[Compito assegnato da Jonatan dal pannello dell'iPhone alla squadra {c['squadra']}] {c['testo']}\n"
                 "Usa gli strumenti di quella squadra. Le azioni critiche passano dalle approvazioni come sempre. "
                 "Alla fine rispondi in breve con cosa hai fatto.")
    try:
        risposta = cervello.chiedi(richiesta)
        c["stato"], c["esito"] = "fatto", risposta[:1500]
        attivita.registra(f"Compito fatto ({c['squadra']}): {c['testo'][:80]}", "telefono", "ok")
    except Exception as e:
        c["stato"], c["esito"] = "errore", str(e)[:300]
        attivita.registra(f"Compito non riuscito ({c['squadra']}): {str(e)[:100]}", "telefono", "errore")
    try:
        from segreteria import telegram_bot
        if telegram_bot.configurato():
            telegram_bot.notifica(f"📱 Compito n.{c['id']} ({c['squadra']}): {c['testo'][:120]}\n\n{c['esito']}")
    except Exception:
        pass


def testo_stato(versione: str = "") -> str:
    """Risposta a /stato su Telegram quando Jarvis è acceso."""
    d = dati()
    ai_ = d.get("ai") or {}
    righe = [f"🟢 Jarvis {versione} acceso da {d['acceso_da']}",
             f"AI in uso: {ai_.get('in_uso', 'claude')} · spesa del mese {ai_.get('spesa_mese', 0):.2f} € su {ai_.get('tetto', 0):.0f} €",
             f"Squadre al lavoro: {sum(1 for s in d['squadre'] if s['attivo'])} · approvazioni in attesa: {d['approvazioni_in_attesa']}"]
    return "\n".join(righe)


def _spegni() -> str:
    """Dopo il SÌ: Jarvis si chiude (il guardiano si ferma; il custode resta acceso e può riaccenderlo)."""
    attivita.registra("Jarvis spento da Telegram", "telefono", "info")
    threading.Timer(3, lambda: os._exit(0)).start()
    return "Spengo Jarvis tra pochi secondi. Per riaccenderlo scrivi /accendi (risponde il custode)."


def chiedi_spegnimento() -> str:
    import approvazioni
    a = approvazioni.richiedi("spegni_jarvis", {}, "Spegnere Jarvis? "
                              "Per riaccenderlo usa /accendi o la pagina dell'iPhone.", scadenza_ore=0.25,
                              chiave="spegni_jarvis")
    return f"Ti ho chiesto conferma (richiesta n.{a['id']})."


try:
    import approvazioni as _ap
    _ap.registra("spegni_jarvis", _spegni)
except Exception as _e:
    print("Pannello, approvazioni:", repr(_e))


def nuovo_compito(squadra: str, testo: str) -> dict:
    testo = (testo or "").strip()[:800]
    if len(testo) < 3:
        return {"errore": "Scrivi il compito."}
    try:
        import squadre
        validi = {s["id"]: s["nome"] for s in squadre.stato()["squadre"]}
    except Exception:
        validi = {}
    nome = validi.get(squadra, "Jarvis decide")
    with _lock:
        c = {"id": (_compiti[-1]["id"] + 1) if _compiti else 1, "squadra": nome, "testo": testo, "stato": "in coda",
             "creato": dt.datetime.now().strftime("%H:%M"), "esito": ""}
        _compiti.append(c)
        del _compiti[:-30]
    threading.Thread(target=_esegui_compito, args=(c,), daemon=True).start()
    return {"ok": True, "id": c["id"], "messaggio": f"Compito n.{c['id']} inviato a {nome}: il risultato arriva su Telegram."}
