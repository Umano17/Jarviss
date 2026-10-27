"""Briefing all'accensione: notizie in pillole, eventi di oggi e riepilogo del lavoro.

All'avvio di Jarvis (una volta al giorno) può arrivare:  sullo schermo, come notifica sul Mac,
a voce e su Telegram, secondo le Impostazioni. Il lunedì può arrivare anche il riepilogo della settimana.
"""
import datetime as dt

import orario
import json
import re
import threading
import time
from pathlib import Path

import impostazioni
import notizie_giorno
import progetti
import uso

FILE_STATO = Path(__file__).parent / "briefing_stato.json"
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def _saluto():
    h = orario.adesso().hour
    return "Buonanotte" if h < 5 else "Buongiorno" if h < 13 else "Buon pomeriggio" if h < 18 else "Buonasera"


def _segno(n):
    return ("+" if n > 0 else "") + f"{n:.2f}".replace(".", ",")


def eventi_oggi():
    """Impegni di oggi dal Calendario del Mac: [{ora, titolo}] oppure (None, errore)."""
    import cervello
    try:
        testo = cervello.agenda_leggi(1)
    except Exception as e:
        return None, str(e)
    if testo.startswith("Errore"):
        return None, "Calendario non leggibile"
    out = []
    for riga in testo.splitlines():
        p = [x.strip() for x in riga.split(" | ")]
        if len(p) < 2:
            continue
        m = re.search(r"(\d{1,2})[:.](\d{2})", p[1])
        ora = f"{int(m.group(1)):02d}:{m.group(2)}" if m else "--:--"
        out.append({"ora": "Giornata" if ora == "00:00" else ora, "titolo": p[0][:90]})
    out.sort(key=lambda e: (e["ora"] != "Giornata", e["ora"]))
    return out, ""


def _lavoro():
    """Reparto Produttività: chi richiamare oggi, incassi del mese, canoni da incassare, bozze da approvare."""
    try:
        import produttivita
        p = produttivita.panoramica()
        k = p["cassa"]
        return {"disponibile": True, "richiami": [c["nome"] for c in p["richiami_oggi"]][:6],
                "incassato_mese": k["incassato_mese"], "mrr": k["mrr"],
                "canoni_da_incassare": len(k["abbonamenti_da_incassare"]),
                "bozze": p["contenuti_da_approvare"]}
    except Exception:
        return {"disponibile": False}


def _lavoro_frase(l):
    if not l.get("disponibile"):
        return ""
    p = []
    if l["richiami"]:
        p.append("Da richiamare oggi: " + ", ".join(l["richiami"]) + ".")
    if l["incassato_mese"] or l["mrr"]:
        p.append(f"Incassato questo mese {l['incassato_mese']:g} euro, canoni mensili {l['mrr']:g} euro.")
    if l["canoni_da_incassare"]:
        p.append(f"{l['canoni_da_incassare']} canoni del mese ancora da incassare.")
    if l["bozze"]:
        p.append(f"{l['bozze']} contenuti in bozza da approvare.")
    return " ".join(p)


def costruisci(con_eventi=True):
    import cervello
    n = notizie_giorno.stato()
    notizie = [{"categoria": x["categoria"], "titolo": x["titolo"]} for x in n["notizie"][:3]]
    eventi, err = eventi_oggi() if con_eventi else (None, "")
    adesso = orario.adesso()
    data = f"{GIORNI[adesso.weekday()]} {adesso.day} {MESI[adesso.month - 1]}"
    b = {"saluto": _saluto(), "nome": cervello.NOME_UTENTE, "data": data, "notizie": notizie,
         "notizie_in_corso": bool(n["in_corso"]), "eventi": (eventi or [])[:5], "eventi_totali": len(eventi or []),
         "eventi_errore": err, "lavoro": _lavoro()}
    b["testo_voce"] = _testo_voce(b)
    b["testo_telegram"] = _testo_telegram(b)
    return b


def _testo_voce(b):
    p = [f"{b['saluto']} {b['nome']}."]
    if b["notizie"]:
        p.append("Notizie in breve. " + " ".join(x["titolo"].rstrip(".") + "." for x in b["notizie"]))
    if b["eventi_errore"]:
        p.append("Non riesco a leggere il Calendario.")
    elif b["eventi"]:
        primo = b["eventi"][0]
        p.append(f"Hai {b['eventi_totali']} impegni oggi" + ("" if primo["ora"] == "Giornata" else f", il primo alle {primo['ora']}") + f": {primo['titolo']}.")
    else:
        p.append("Nessun impegno in calendario oggi.")
    if _lavoro_frase(b.get("lavoro", {})):
        p.append(_lavoro_frase(b["lavoro"]))
    return " ".join(p)


def _testo_telegram(b):
    r = [f"{b['saluto']} {b['nome']} — {b['data']}", ""]
    if b["notizie"]:
        r.append("NOTIZIE")
        r += [f"• [{x['categoria']}] {x['titolo']}" for x in b["notizie"]]
        r.append("")
    r.append("EVENTI")
    r += ([f"• {e['ora']} {e['titolo']}" for e in b["eventi"]] or ["• nessun impegno oggi"]) if not b["eventi_errore"] else ["• Calendario non leggibile"]
    if _lavoro_frase(b.get("lavoro", {})):
        r += ["", "LAVORO", _lavoro_frase(b["lavoro"])]
    return "\n".join(r)


# ---------------------------------------------------------------- invii

def invia_telegram(testo):
    try:
        from segreteria import notifica
        notifica(testo)
        return True
    except Exception as e:
        print("Briefing: Telegram non disponibile:", e)
        return False


def notifica_mac(testo):
    try:
        import cervello
        pulito = testo.replace('"', "'").replace("\\", "")[:180]
        cervello.osa(f'display notification "{pulito}" with title "Jarvis"')
    except Exception as e:
        print("Briefing: notifica Mac non riuscita:", e)


def _riassunto_corto(b):
    parti = []
    if b["notizie"]:
        parti.append(f"{len(b['notizie'])} notizie")
    parti.append(f"{b['eventi_totali']} impegni" if not b["eventi_errore"] else "calendario non leggibile")
    return "Briefing pronto: " + " · ".join(parti)


# ---------------------------------------------------------------- stato (una volta al giorno)

def _stato():
    try:
        return json.loads(FILE_STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _salva_stato(**kw):
    s = _stato()
    s.update(kw)
    FILE_STATO.write_text(json.dumps(s), encoding="utf-8")


def _avvio_giornaliero():
    imp = impostazioni.carica()
    if not any(imp[k] == "1" for k in ("briefMac", "briefVoce", "briefTg")):
        return
    oggi = orario.oggi().isoformat()
    if _stato().get("giorno") == oggi or orario.adesso().hour < 5:
        return
    # le notizie si aggiornano all'avvio: le aspetto, ma non più di tre minuti
    limite = time.time() + 180
    time.sleep(10)
    while time.time() < limite:
        s = notizie_giorno.stato()
        if s["notizie"] and not s["in_corso"]:
            break
        if not s["in_corso"] and not s["notizie"] and time.time() > limite - 150:
            break
        time.sleep(5)
    b = costruisci()
    if imp["briefMac"] == "1":
        notifica_mac(_riassunto_corto(b))
    if imp["briefTg"] == "1":
        invia_telegram(b["testo_telegram"])
    if imp["briefVoce"] == "1":
        import voce_jarvis
        for _ in range(60):
            if voce_jarvis.motore_attivo():
                voce_jarvis.parla(b["testo_voce"])
                break
            time.sleep(2)
    _salva_stato(giorno=oggi)
    try:
        import attivita
        attivita.registra("Briefing del giorno preparato", "briefing", "ok")
    except Exception:
        pass


# ---------------------------------------------------------------- riepilogo della settimana

def riepilogo_settimanale():
    r = ["RIEPILOGO DELLA SETTIMANA", ""]
    u = uso.riepilogo(7)
    top = [p for p in u["reparti"] if p["richieste"]][:3]
    if top:
        def riga(p):
            costo = f", {p['costo']} {u['valuta']}" if p["costo"] is not None else ""
            return f"{p['reparto']} ({p['richieste']} richieste, {(p['token_in'] + p['token_out']) // 1000}k token{costo})"
        r.append("Uso: " + "; ".join(riga(p) for p in top) + ".")
    fermi = [p for p in progetti.elenco() if p.get("aggiornato", "")[:10] < (dt.date.today() - dt.timedelta(days=7)).isoformat()]
    if fermi:
        r.append("Progetti fermi da più di 7 giorni: " + ", ".join(p["nome"] for p in fermi[:5]) + ".")
    fb = sum(1 for p in progetti.elenco() for f in p.get("feedback", []) if f["ts"][:10] >= (dt.date.today() - dt.timedelta(days=7)).isoformat())
    if fb:
        r.append(f"Feedback ricevuti nella settimana: {fb}.")
    return "\n".join(r)


def _controllo_settimanale():
    ora = orario.adesso()
    sett = f"{ora.isocalendar().year}-W{ora.isocalendar().week}"
    if impostazioni.carica()["riepSett"] == "1" and ora.weekday() == 0 and ora.hour >= 8 and _stato().get("settimana") != sett:
        if invia_telegram(riepilogo_settimanale()):
            _salva_stato(settimana=sett)


def _ciclo():
    time.sleep(8)
    try:
        _avvio_giornaliero()
    except Exception as e:
        print("Briefing, errore:", repr(e))
    while True:
        try:
            _controllo_settimanale()
        except Exception as e:
            print("Riepilogo settimanale, errore:", repr(e))
        time.sleep(1800)


def avvia():
    threading.Thread(target=_ciclo, daemon=True).start()
