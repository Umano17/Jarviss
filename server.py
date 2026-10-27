"""Server locale di Jarvis 3.9: mostra la schermata e le passa le richieste."""
import datetime as dt
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context, abort

import cervello
import notizie_giorno
import voce_jarvis
import siti
import rubrica
import progetti
import uso
import impostazioni
import briefing
import squadre
import approvazioni
import manutentore
import produttivita as prod
import memoria
import seo_locale
import pubblica
import pannello           # dati per la pagina dell'iPhone (servita dal custode) e compiti alle squadre
import aggiornamenti      # /aggiorna da Telegram con SÌ/NO (registra l'azione nelle approvazioni)
from skills_loader import gestore as skill

BASE = Path(__file__).parent
app = Flask(__name__)
VERSIONE = "3.9"
PORTA = 8765
HOST_AMMESSI = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
ORIGINI_AMMESSE = {f"http://{h}" for h in HOST_AMMESSI}


@app.before_request
def solo_da_questo_mac():
    """Blocca le richieste che non arrivano dalla schermata di Jarvis.
    Senza questo controllo, qualsiasi sito aperto in Chrome potrebbe far partire ricerche a pagamento o
    inviare richieste chiamando http://127.0.0.1:8765 di nascosto."""
    if request.host not in HOST_AMMESSI:
        abort(403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origine = request.headers.get("Origin")
        if origine is not None and origine not in ORIGINI_AMMESSE:
            abort(403)
        if origine is None and request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            abort(403)


def evento(dati):
    return "data: " + json.dumps(dati, ensure_ascii=False) + "\n\n"


@app.route("/")
def home():
    return send_from_directory(BASE, "interfaccia.html")


@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True, "versione": VERSIONE})


# ---------------- File: quello che Jarvis genera, da vedere e scaricare (solo da questo Mac)

CARTELLE_FILE = [("demo", "Demo siti", BASE / "demo"), ("progetti", "Progetti", BASE / "progetti"),
                 ("seo", "Rapporti SEO", BASE / "dati" / "seo"),
                 ("manutenzione", "Manutenzione", BASE / "dati" / "manutenzione")]
MAX_FILE = 400


def _cartella_di(p: Path):
    for cid, _, radice in CARTELLE_FILE:
        try:
            p.relative_to(radice.resolve())
            return cid
        except ValueError:
            continue
    return None


@app.route("/api/file")
def api_file():
    out = []
    for cid, nome, radice in CARTELLE_FILE:
        if not radice.is_dir():
            continue
        for f in radice.rglob("*"):
            if any(x.startswith(".") for x in f.relative_to(radice).parts) or not f.is_file() or f.is_symlink():
                continue
            st = f.stat()
            out.append({"cartella": cid, "nome": f.name, "percorso": str(f.relative_to(BASE)), "byte": st.st_size,
                        "t": st.st_mtime,
                        "modificato": dt.datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")})
    out.sort(key=lambda x: -x["t"])
    return jsonify({"cartelle": [{"id": c, "nome": n} for c, n, r in CARTELLE_FILE if r.is_dir()],
                    "file": out[:MAX_FILE], "troncato": len(out) > MAX_FILE})


@app.route("/api/file/scarica")
def api_file_scarica():
    """Scarica un file solo se sta dentro una delle cartelle ammesse (niente .env, chiavi o dati personali)."""
    rel = request.args.get("p", "")
    try:
        p = (BASE / rel).resolve(strict=True)
    except (OSError, RuntimeError):
        abort(404)
    if not p.is_file() or _cartella_di(p) is None or any(x.startswith(".") for x in Path(rel).parts):
        abort(404)
    return send_from_directory(p.parent, p.name, as_attachment=True)


@app.route("/api/pannello")
def api_pannello():
    d = pannello.dati()
    d["versione"] = VERSIONE
    return jsonify(d)


@app.route("/api/pannello/compito", methods=["POST"])
def api_pannello_compito():
    d = request.get_json(silent=True) or {}
    return jsonify(pannello.nuovo_compito(str(d.get("squadra", ""))[:40], str(d.get("testo", ""))))


@app.route("/api/salute")
def api_salute():
    """Controllo usato dal guardiano (avvio.py) dopo un aggiornamento: risponde solo se i moduli sono carichi."""
    return jsonify({"ok": True, "versione": VERSIONE, "pronto": True})


# ---------------- conversazione (a pezzetti, per rispondere subito)

@app.route("/api/chiedi_stream", methods=["POST"])
def api_chiedi_stream():
    testo = (request.get_json(silent=True) or {}).get("testo", "").strip()

    def genera():
        if not testo:
            yield evento({"tipo": "testo", "testo": "Non ho sentito nulla, puoi ripetere?"})
        else:
            try:
                from segreteria import gestisci as segreteria_gestisci

                # «sì» / «no» detto subito dopo una richiesta di approvazione: decide l'utente, non il modello
                decisione = approvazioni.risposta_testo(testo, "schermo", entro_min=10)
                risposta_segreteria = decisione if decisione is not None else segreteria_gestisci(testo)
                if risposta_segreteria is not None:
                    # usa risposta_segreteria come risposta di Jarvis (la pronuncia lui)
                    yield evento({"tipo": "testo", "testo": risposta_segreteria})
                else:
                    for ev in cervello.chiedi_stream(testo):
                        yield evento(ev)
            except Exception as e:
                print("ERRORE:", e)
                yield evento({"tipo": "testo", "testo": " Ho avuto un problema tecnico. Controlla il Terminale."})
        yield evento({"tipo": "fine"})

    return Response(
        stream_with_context(genera()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/chiedi", methods=["POST"])
def api_chiedi():
    testo = (request.get_json(silent=True) or {}).get("testo", "").strip()
    if not testo:
        return jsonify({"risposta": "Non ho sentito nulla, puoi ripetere?"})
    try:
        from segreteria import gestisci as segreteria_gestisci

        risposta_segreteria = segreteria_gestisci(testo)
        if risposta_segreteria is not None:
            # usa risposta_segreteria come risposta di Jarvis (la pronuncia lui)
            risposta = risposta_segreteria
        else:
            risposta = cervello.chiedi(testo)
    except Exception as e:
        print("ERRORE:", e)
        risposta = "Ho avuto un problema tecnico. Controlla il Terminale per i dettagli."
    return jsonify({"risposta": risposta})


@app.route("/api/azzera", methods=["POST"])
def api_azzera():
    cervello.azzera()
    return jsonify({"ok": True})


@app.route("/api/notizie/giorno")
def api_notizie_giorno():
    return jsonify(notizie_giorno.stato())


@app.route("/api/notizie/giorno/aggiorna", methods=["POST"])
def api_notizie_giorno_aggiorna():
    notizie_giorno.aggiorna(forza=True)
    return jsonify(notizie_giorno.stato())


# ---------------- agenda di oggi (letta dall'app Calendario, con una piccola cache)

_agenda = {"t": 0, "dati": None}


@app.route("/api/agenda/oggi")
def api_agenda_oggi():
    if _agenda["dati"] is not None and time.time() - _agenda["t"] < 300 and not request.args.get("forza"):
        return jsonify(_agenda["dati"])
    try:
        testo = cervello.agenda_leggi(1)
    except Exception as e:
        testo = "Errore: " + str(e)
    if testo.startswith("Errore"):
        return jsonify({"errore": "Non riesco a leggere il Calendario: consenti l'accesso al Terminale in Impostazioni di Sistema > Privacy > Calendari."})
    def ora_di(t):
        m = re.search(r"(\d{1,2})[:.](\d{2})", t or "")
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""

    eventi = []
    for riga in testo.splitlines():
        parti = [x.strip() for x in riga.split(" | ")]
        if len(parti) < 2:
            continue
        inizio, fine = ora_di(parti[1]), ora_di(parti[2] if len(parti) > 2 else "")
        giornata = inizio == "00:00" and fine in ("", "00:00")
        eventi.append({"titolo": parti[0], "ora": "Giornata" if giornata else (inizio or "--:--"),
                       "fine": "" if giornata else fine, "luogo": parti[3] if len(parti) > 3 and parti[3] != "missing value" else "",
                       "sovrapposto": False, "_i": inizio, "_f": fine or inizio, "_g": giornata})
    eventi.sort(key=lambda e: (not e["_g"], e["_i"]))
    con_orario = [e for e in eventi if not e["_g"]]
    for i, a in enumerate(con_orario):
        for b in con_orario[i + 1:]:
            if b["_i"] < a["_f"]:
                a["sovrapposto"] = b["sovrapposto"] = True
    for e in eventi:
        for k in ("_i", "_f", "_g"):
            e.pop(k)
    _agenda.update(t=time.time(), dati={"eventi": eventi})
    return jsonify(_agenda["dati"])


@app.after_request
def intestazioni(r):
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("Referrer-Policy", "no-referrer")
    return r


# ---------------- impostazioni della schermata

@app.route("/api/impostazioni", methods=["GET", "POST"])
def api_impostazioni():
    if request.method == "POST":
        return jsonify(impostazioni.salva(request.get_json(silent=True) or {}))
    return jsonify(impostazioni.carica())


# ---------------- briefing (notizie in pillole, eventi)

_brief = {"t": 0, "dati": None}


@app.route("/api/briefing")
def api_briefing():
    if _brief["dati"] is None or time.time() - _brief["t"] > 45 or request.args.get("forza"):
        try:
            _brief.update(t=time.time(), dati=briefing.costruisci())
        except Exception as e:
            print("BRIEFING:", e)
            return jsonify({"errore": "Non riesco a preparare il briefing."})
    return jsonify(_brief["dati"])


@app.route("/api/briefing/telegram", methods=["POST"])
def api_briefing_telegram():
    b = _brief["dati"] or briefing.costruisci()
    return jsonify({"ok": briefing.invia_telegram(b["testo_telegram"])})


@app.route("/api/riepilogo/telegram", methods=["POST"])
def api_riepilogo_telegram():
    return jsonify({"ok": briefing.invia_telegram(briefing.riepilogo_settimanale())})


# ---------------- lead dalle mappe (ricerca in sottofondo, foglio su Drive)

_lead = {"in_corso": False, "errore": "", "ultimo": None, "inizio": 0}
_lead_lock = threading.Lock()


def _lavora_lead(d):
    import lead_maps
    ultimo, errore = None, ""
    try:
        ris = lead_maps.cerca(d.get("categorie"), d.get("localita"), d.get("limite", 60), d.get("sito", "tutti"),
                              solo_telefono=bool(d.get("solo_telefono")))
        if "errore" in ris:
            errore = ris["errore"]
        else:
            esito = lead_maps.salva(ris, nei_clienti=bool(d.get("nei_clienti", True)))
            ultimo = {"criteri": ris["criteri"], "righe": ris["righe"], "trovate": ris["trovate"],
                      "verificate": ris["verificate"], "scarti": ris["scarti"], "esito": esito,
                      "testo": lead_maps.testo_per_jarvis(ris, esito)}
    except RuntimeError as e:
        errore = str(e)
    except Exception as e:
        print("LEAD:", repr(e))
        errore = "Ricerca non riuscita: guarda il Terminale."
    with _lead_lock:
        _lead.update(in_corso=False, errore=errore, ultimo=ultimo or _lead["ultimo"])


def _lead_json():
    import lead_maps
    with _lead_lock:
        return {**_lead, "storico": lead_maps.storico(), "fonte": "google" if lead_maps.chiave() else "osm",
                "categorie": lead_maps.CATEGORIE_ESEMPIO}


@app.route("/api/lead")
def api_lead():
    return jsonify(_lead_json())


@app.route("/api/lead/cerca", methods=["POST"])
def api_lead_cerca():
    d = request.get_json(silent=True) or {}
    if not str(d.get("categorie", "")).strip() or not str(d.get("localita", "")).strip():
        return jsonify({"errore": "Servono almeno una categoria e una località."}), 400
    with _lead_lock:
        if _lead["in_corso"]:
            return jsonify({"errore": "C'è già una ricerca in corso."}), 409
        _lead.update(in_corso=True, errore="", inizio=time.time())
    threading.Thread(target=_lavora_lead, args=(d,), daemon=True).start()
    return jsonify(_lead_json())


# ---------------- rubrica

@app.route("/api/rubrica", methods=["GET", "POST"])
def api_rubrica():
    if request.method == "POST":
        c, err = rubrica.aggiungi(request.get_json(silent=True) or {})
        return (jsonify({"errore": err}), 400) if err else jsonify(c)
    return jsonify({"contatti": rubrica.elenco(request.args.get("q", ""))})


@app.route("/api/rubrica/<int:id_>", methods=["PUT", "DELETE"])
def api_rubrica_id(id_):
    if request.method == "DELETE":
        return jsonify({"ok": rubrica.elimina(id_)})
    c, err = rubrica.modifica(id_, request.get_json(silent=True) or {})
    return (jsonify({"errore": err}), 400) if err else jsonify(c)


# ---------------- progetti (cartella sul Mac e su Drive, condivisa dagli agenti)

@app.route("/api/progetti", methods=["GET", "POST"])
def api_progetti():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        cliente = d.get("cliente") if isinstance(d.get("cliente"), int) else None
        ag = d.get("agenti") if isinstance(d.get("agenti"), list) else None
        p, err = progetti.crea(d.get("nome", ""), d.get("tipo", "altro"), cliente, ag)
        return (jsonify({"errore": err}), 400) if err else jsonify(p)
    lista = []
    for p in progetti.elenco():
        lista.append({k: p[k] for k in ("id", "nome", "tipo", "cliente", "agenti", "creato", "aggiornato", "drive")}
                     | {"feedback": len(p["feedback"]), "tipo_nome": progetti.TIPI[p["tipo"]]["nome"]})
    return jsonify({"progetti": lista, "agenti": progetti.AGENTI, "drive_pronto": progetti.drive_pronto(),
                    "tipi": {k: {"nome": v["nome"], "agenti": v["agenti"], "cartelle": v["cartelle"]} for k, v in progetti.TIPI.items()}})


@app.route("/api/progetti/<int:id_>")
def api_progetto(id_):
    p = progetti.dettaglio(id_)
    return jsonify(p) if p else (jsonify({"errore": "Progetto non trovato."}), 404)


@app.route("/api/progetti/<int:id_>/feedback", methods=["POST"])
def api_progetto_feedback(id_):
    ok = progetti.aggiungi_feedback(id_, (request.get_json(silent=True) or {}).get("testo", ""))
    return jsonify(progetti.dettaglio(id_)) if ok else (jsonify({"errore": "Scrivi il feedback."}), 400)


@app.route("/api/progetti/<int:id_>/agente", methods=["POST"])
def api_progetto_agente(id_):
    d = request.get_json(silent=True) or {}
    p = progetti.collega_agente(id_, d.get("agente", ""), bool(d.get("on", True)))
    return jsonify(p) if p else (jsonify({"errore": "Progetto o agente non valido."}), 400)


@app.route("/api/progetti/<int:id_>/drive", methods=["POST"])
def api_progetto_drive(id_):
    return jsonify({"ok": progetti.sincronizza(id_)})


# ---------------- uso per reparto

@app.route("/api/uso")
def api_uso():
    try:
        giorni = max(1, min(365, int(request.args.get("giorni", 30))))
    except ValueError:
        giorni = 30
    d = uso.riepilogo(giorni)
    try:
        import ai
        d["ai"] = ai.stato()            # Claude + riserve, AI in uso adesso, spesa del mese e tetto
    except Exception as e:
        print("AI, stato:", repr(e))
    return jsonify(d)


# ---------------- coda "Da approvare" (email in attesa del tuo sì)

@app.route("/api/approvazioni")
def api_approvazioni():
    try:
        from segreteria import bozza_in_attesa
        return jsonify({"email": bozza_in_attesa()})
    except Exception:
        return jsonify({"email": None})


@app.route("/api/approvazioni/richieste")
def api_richieste():
    return jsonify({"in_attesa": approvazioni.in_attesa(), "recenti": approvazioni.recenti()})


@app.route("/api/approvazioni/richieste/<int:id_>", methods=["POST"])
def api_richiesta_decidi(id_):
    si = (request.get_json(silent=True) or {}).get("si")
    if si not in (True, False):
        return jsonify({"errore": "Serve si: true oppure false."}), 400
    return jsonify({"messaggio": approvazioni.decidi(id_, si, "schermo")})


@app.route("/api/approvazioni/richieste/<int:id_>/codice", methods=["POST"])
def api_richiesta_codice(id_):
    """Codice di verifica della zona sacra, scritto sulla schermata."""
    codice = str((request.get_json(silent=True) or {}).get("codice", ""))[:12]
    return jsonify({"messaggio": approvazioni.verifica_codice(id_, codice, "schermo")})


@app.route("/api/approvazioni/email/<azione>", methods=["POST"])
def api_approvazioni_email(azione):
    if azione not in ("invia", "annulla"):
        abort(404)
    from segreteria import approva, scarta
    return jsonify({"messaggio": approva() if azione == "invia" else scarta()})


# ---------------- collegamenti (cosa è collegato davvero)

@app.route("/api/collegamenti")
def api_collegamenti():
    out = {"telegram": False, "gmail": False, "drive": False}
    try:
        from segreteria import configurato, google_account
        out["telegram"] = bool(configurato())
        out["gmail"] = out["drive"] = bool(google_account.token_presente())
    except Exception:
        pass
    return jsonify(out)


# ---------------- skill (cartella skills/, widget Skill e Siti web)

@app.route("/api/skills")
def api_skills():
    return jsonify(skill.stato(request.args.get("categoria")))


@app.route("/api/skills/ricarica", methods=["POST"])
def api_skills_ricarica():
    skill.ricarica()
    return jsonify(skill.stato(request.args.get("categoria")))


@app.route("/api/skills/disattiva", methods=["POST"])
def api_skills_disattiva():
    skill.disattiva()
    return jsonify(skill.stato(request.args.get("categoria")))


@app.route("/api/skills/<nome>/attiva", methods=["POST"])
def api_skills_attiva(nome):
    try:
        skill.attiva(nome)
    except KeyError as e:
        return jsonify({"errore": str(e).strip("'\"")}), 404
    return jsonify(skill.stato(request.args.get("categoria")))


# ---------------- siti web: demo per attività locali

@app.route("/api/siti")
def api_siti():
    return jsonify(siti.stato())


@app.route("/api/siti/crea", methods=["POST"])
def api_siti_crea():
    d = request.get_json(silent=True) or {}
    pid = d.get("progetto_id") if isinstance(d.get("progetto_id"), int) else None
    r = siti.crea(d.get("nome", ""), d.get("citta", ""), d.get("nota", ""), bool(d.get("forza")), pid,
                  stile=d.get("stile", "auto"), livello=d.get("livello", "3"), riusa=bool(d.get("riusa")))
    return jsonify(r), (400 if r.get("errore") else 200)


FILE_DEMO = {"index.html": "text/html", "scheda.md": "text/plain", "messaggio.txt": "text/plain"}


@app.route("/demo/<slug>/<nome_file>")
def demo_file(slug, nome_file):
    if nome_file not in FILE_DEMO or slug != siti.slug(slug):
        abort(404)
    r = send_from_directory(siti.CARTELLA / slug, nome_file, mimetype=FILE_DEMO[nome_file] + "; charset=utf-8")
    # la demo è codice generato: la apriamo "in una scatola chiusa", senza accesso alle funzioni di Jarvis
    r.headers["Content-Security-Policy"] = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
                                            "connect-src 'none'; form-action 'none'")
    r.headers["Cache-Control"] = "no-store"
    return r


def _demo_chiusa(r):
    r.headers["Content-Security-Policy"] = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
                                            "connect-src 'none'; form-action 'none'")
    r.headers["Cache-Control"] = "no-store"
    return r


@app.route("/demo/<slug>/personalizzata/")
@app.route("/demo/<slug>/personalizzata/index.html")
def demo_personalizzata(slug):
    if slug != siti.slug(slug) or not (siti.CARTELLA / slug / "personalizzata" / "index.html").exists():
        abort(404)
    return _demo_chiusa(send_from_directory(siti.CARTELLA / slug / "personalizzata", "index.html",
                                            mimetype="text/html; charset=utf-8"))


@app.route("/demo/<slug>/personalizzata/img/<nome_file>")
def demo_personalizzata_img(slug, nome_file):
    if slug != siti.slug(slug) or not re.fullmatch(r"[a-z0-9-]+-\d+\.webp", nome_file):
        abort(404)
    return send_from_directory(siti.CARTELLA / slug / "personalizzata" / "img", nome_file, mimetype="image/webp")


# ---------------- squadre degli agenti e squadra Support (Sala controllo)

@app.route("/api/squadre")
def api_squadre():
    return jsonify(squadre.stato())


@app.route("/api/squadre/ricarica", methods=["POST"])
def api_squadre_ricarica():
    squadre.carica()
    return jsonify(squadre.stato())


# ---------------- PRODUTTIVITÀ (3.5): clienti, contenuti, testi, SEO locale, listino, preventivi, incassi, memoria

def _d():
    return request.get_json(silent=True) or {}


def _ris(x, err=""):
    """Risposta standard: oggetto oppure {"errore": ...} con codice 400."""
    if err or x is None:
        return jsonify({"errore": err or "Non trovato."}), 400
    return jsonify(x)


def _id_cliente(v):
    return int(v) if str(v or "").isdigit() else None


@app.route("/api/prod")
def api_prod():
    return jsonify(prod.panoramica())


@app.route("/api/prod/job/<jid>")
def api_prod_job(jid):
    return jsonify(prod.stato_job(jid))


@app.route("/api/prod/clienti", methods=["GET", "POST"])
def api_prod_clienti():
    if request.method == "POST":
        d = _d()
        c, err = prod.aggiungi_cliente(d.get("nome"), d.get("citta", ""), d.get("categoria", ""), d.get("telefono", ""),
                                       d.get("email", ""), d.get("note", ""), d.get("stato", "trovato"))
        return _ris(c, err)
    prod.sincronizza_demo()
    return jsonify({"clienti": prod.clienti(), "stati": prod.STATI_CLIENTE})


@app.route("/api/prod/clienti/<int:id_>", methods=["POST"])
def api_prod_cliente(id_):
    d = _d()
    if d.get("elimina"):
        return jsonify({"ok": prod.elimina_cliente(id_)})
    if d.get("richiamo_fatto"):
        return _ris(*prod.richiamo_fatto(id_, d.get("esito", "")))
    campi = {k: d.get(k) for k in ("stato", "nota", "note", "richiamo", "telefono", "email", "citta", "categoria", "link_demo", "valore") if k in d}
    return _ris(*prod.aggiorna_cliente(id_, **campi))


@app.route("/api/prod/clienti/<int:id_>/messaggio", methods=["POST"])
def api_prod_messaggio(id_):
    d = _d()
    return jsonify({"job": prod.avvia_job("Messaggio per un cliente", prod.prepara_messaggio, id_, d.get("tipo", "primo"),
                                          d.get("canale", "whatsapp"), d.get("nota", ""))})


@app.route("/api/prod/contenuti", methods=["GET", "POST"])
def api_prod_contenuti():
    if request.method == "POST":
        d = _d()
        if not str(d.get("argomento", "")).strip():
            return jsonify({"errore": "Serve l'argomento."}), 400
        return jsonify({"job": prod.avvia_job(f"{d.get('tipo', 'Contenuto')}: {str(d.get('argomento'))[:40]}", prod.crea_contenuto,
                                              d.get("tipo"), d.get("argomento"), _id_cliente(d.get("cliente_id")), d.get("nota", ""))})
    return jsonify({"contenuti": prod.contenuti()[:100], "tipi": prod.TIPI_CONTENUTO, "ricorrenti": prod.ricorrenti()})


@app.route("/api/prod/contenuti/<int:id_>", methods=["POST"])
def api_prod_contenuto(id_):
    d = _d()
    if d.get("elimina"):
        return jsonify({"ok": prod.elimina_contenuto(id_)})
    return _ris(prod.aggiorna_contenuto(id_, d.get("stato"), d.get("testo")))


@app.route("/api/prod/ricorrenti", methods=["POST"])
def api_prod_ricorrenti():
    d = _d()
    if d.get("id"):
        return _ris(prod.imposta_ricorrente(d["id"], bool(d.get("attivo"))))
    return _ris(*prod.crea_ricorrente(_id_cliente(d.get("cliente_id")), d.get("tipo"), d.get("quantita", 4),
                                      d.get("giorno", 1), d.get("guida", "")))


@app.route("/api/prod/lavori", methods=["GET", "POST"])
def api_prod_lavori():
    if request.method == "POST":
        d = _d()
        if not str(d.get("brief", "")).strip():
            return jsonify({"errore": "Serve il brief."}), 400
        return jsonify({"job": prod.avvia_job(f"{d.get('servizio', 'Lavoro')}: {str(d.get('titolo') or '')[:40]}", prod.crea_lavoro,
                                              d.get("servizio"), d.get("titolo", ""), d.get("brief"), _id_cliente(d.get("cliente_id")))})
    return jsonify({"lavori": prod.lavori()[:100], "servizi": prod.SERVIZI_TESTI})


@app.route("/api/prod/lavori/<int:id_>", methods=["POST"])
def api_prod_lavoro(id_):
    d = _d()
    if d.get("elimina"):
        return jsonify({"ok": prod.elimina_lavoro(id_)})
    if d.get("feedback"):
        return jsonify({"job": prod.avvia_job("Revisione di un lavoro", prod.rivedi_lavoro, id_, d["feedback"])})
    return _ris(prod.stato_lavoro(id_, d.get("stato", "")))


@app.route("/api/prod/seo", methods=["GET", "POST"])
def api_prod_seo():
    if request.method == "POST":
        d = _d()
        return jsonify({"job": prod.avvia_job(f"SEO locale: {str(d.get('nome', ''))[:40]}", seo_locale.analizza,
                                              d.get("nome", ""), d.get("citta", ""), _id_cliente(d.get("cliente_id")))})
    return jsonify({"rapporti": seo_locale.rapporti()})


@app.route("/api/prod/seo/<nome_file>")
def api_prod_seo_file(nome_file):
    t = seo_locale.leggi(nome_file)
    if t is None:
        abort(404)
    return Response(t, mimetype="text/plain; charset=utf-8")


@app.route("/api/prod/listino", methods=["GET", "POST"])
def api_prod_listino():
    if request.method == "POST":
        d = _d()
        return _ris(*prod.aggiorna_voce(d.get("id", ""), prezzo=d.get("prezzo"), nome=d.get("nome"), unita=d.get("unita"),
                                        nuova=bool(d.get("nuova")), gruppo=d.get("gruppo", "Altro")))
    return jsonify({"listino": prod.listino()})


@app.route("/api/prod/preventivi", methods=["GET", "POST"])
def api_prod_preventivi():
    if request.method == "POST":
        d = _d()
        return _ris(*prod.crea_preventivo(_id_cliente(d.get("cliente_id")), d.get("voci", []), d.get("note", "")))
    return jsonify({"preventivi": prod.preventivi()})


@app.route("/api/prod/preventivi/<int:id_>", methods=["POST"])
def api_prod_preventivo(id_):
    d = _d()
    return _ris(*prod.aggiorna_preventivo(id_, d.get("stato"), d.get("link_pagamento"), d.get("note")))


@app.route("/preventivo/<int:id_>")
def pagina_preventivo(id_):
    """Preventivo pronto da stampare o salvare in PDF (Cmd+P dal browser)."""
    p = prod.preventivo(id_)
    if not p:
        abort(404)
    import html as _h
    e = _h.escape
    righe = "".join(f"<tr><td>{e(r['descrizione'])}</td><td>{r['quantita']}</td><td>{e(prod._euro(r['prezzo']))}"
                    f"{' / mese' if r['unita'] == 'mese' else ''}</td></tr>" for r in p["righe"])
    pag = (f"<!doctype html><html lang='it'><meta charset='utf-8'><title>Preventivo {e(p['numero'])}</title>"
           "<style>body{font:15px/1.6 -apple-system,Helvetica,Arial,sans-serif;color:#111;max-width:760px;margin:40px auto;padding:0 24px}"
           "h1{font-size:26px;margin:0 0 4px}table{width:100%;border-collapse:collapse;margin:24px 0}td,th{border-bottom:1px solid #ddd;padding:10px 6px;text-align:left}"
           "th{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#555}.tot{font-size:18px;font-weight:600}.n{color:#555;font-size:13px}"
           "@media print{a{color:#111}}</style>"
           f"<h1>Preventivo {e(p['numero'])}</h1><div class='n'>Data {e(p['creato'][:10])} · valido fino al {e(p['valido_fino'])}</div>"
           f"<p>Per: <b>{e(p['cliente'])}</b><br>Da: {e(cervello.NOME_UTENTE)}</p>"
           f"<table><tr><th>Voce</th><th>Q.tà</th><th>Prezzo</th></tr>{righe}</table>"
           f"<p class='tot'>Totale una tantum: {e(prod._euro(p['una_tantum']))}</p>"
           + (f"<p class='tot'>Canone mensile: {e(prod._euro(p['mensile']))}</p>" if p["mensile"] else "")
           + "<p class='n'>Prezzi IVA esclusa.</p>"
           + (f"<p>{e(p['note'])}</p>" if p.get("note") else "")
           + (f"<p>Pagamento online: <a href='{e(p['link_pagamento'])}'>{e(p['link_pagamento'])}</a></p>" if p.get("link_pagamento") else "")
           + "</html>")
    r = Response(pag, mimetype="text/html; charset=utf-8")
    r.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return r


@app.route("/api/prod/cassa", methods=["GET", "POST"])
def api_prod_cassa():
    if request.method == "POST":
        d = _d()
        if d.get("abbonamento_pagato"):
            return _ris(*prod.abbonamento_pagato(d["abbonamento_pagato"]))
        if d.get("abbonamento_stato"):
            return _ris(prod.stato_abbonamento(d.get("id"), d["abbonamento_stato"]))
        if d.get("abbonamento_nuovo"):
            return _ris(*prod.crea_abbonamento(_id_cliente(d.get("cliente_id")), d.get("descrizione", ""), d.get("prezzo_mese")))
        return _ris(*prod.registra_incasso(_id_cliente(d.get("cliente_id")), d.get("importo"), d.get("descrizione", ""), data=d.get("data", "")))
    return jsonify({"cassa": prod.cassa(), "abbonamenti": prod.abbonamenti(), "incassi": prod.incassi()[:60],
                    "margine": prod.margine()})


@app.route("/api/prod/memoria", methods=["GET", "POST"])
def api_prod_memoria():
    if request.method == "POST":
        d = _d()
        if d.get("elimina"):
            return jsonify({"ok": memoria.elimina(d["elimina"])})
        if d.get("id"):
            return _ris(memoria.modifica(d["id"], titolo=d.get("titolo"), testo=d.get("testo"), categoria=d.get("categoria")))
        return _ris(*memoria.salva(d.get("titolo", ""), d.get("testo", ""), d.get("categoria", "altro")))
    return jsonify({"note": memoria.elenco(), "categorie": memoria.CATEGORIE})


@app.route("/api/siti/<slug>/pubblica", methods=["POST"])
def api_siti_pubblica(slug):
    if slug != siti.slug(slug):
        abort(404)
    return jsonify({"job": prod.avvia_job(f"Pubblico la demo {slug}", pubblica.pubblica, slug)})


# ---------------- voce (motore vocale JarvisVoce su questo Mac)

@app.route("/api/voce/stato")
def api_voce_stato():
    try:
        with urllib.request.urlopen(voce_jarvis.URL + "/voci", timeout=2) as r:
            s = json.loads(r.read())
        attiva = next((v for v in s["voci"] if v["id"] == s["attiva"]), None)
        return jsonify({"attivo": True, "voce": attiva["nome"] if attiva else s["attiva"],
                        "pronta": bool(attiva and attiva["pronta"])})
    except Exception:
        return jsonify({"attivo": False})


@app.route("/api/voce/audio", methods=["POST"])
def api_voce_audio():
    testo = (request.get_json(silent=True) or {}).get("testo", "").strip()
    if not testo:
        return jsonify({"errore": "testo vuoto"}), 400
    try:
        richiesta = urllib.request.Request(
            voce_jarvis.URL + "/audio", data=json.dumps({"testo": testo}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(richiesta, timeout=120) as r:
            return Response(r.read(), mimetype="audio/wav")
    except Exception as e:
        return jsonify({"errore": str(e)}), 503


@app.route("/icone/<path:nome>")
def icone(nome):
    return send_from_directory(BASE / "icone", nome)


@app.route("/api/manutenzione")
def manutenzione_stato():
    return jsonify(manutentore.ultimo() or {})


@app.route("/api/manutenzione/controlla", methods=["POST"])
def manutenzione_controlla():
    return jsonify(manutentore.giro(pulisci=False))


if __name__ == "__main__":
    notizie_giorno.avvia()
    briefing.avvia()
    threading.Thread(target=voce_jarvis.avvia_motore, daemon=True).start()   # la voce si accende da sola, se installata
    print(f"Skill: {len(skill.skills)} caricate dalla cartella skills.")
    squadre.avvia()
    prod.avvia()          # contenuti ricorrenti del mese (solo bozze)
    threading.Thread(target=progetti.condividi_esistenti, daemon=True).start()   # cartelle Drive aperte a chi ha il link
    manutentore.avvia()   # controlli ogni ora + pulizia sicura + proposte dell'Architetto il lunedì
    print(f"Squadre: {len(squadre.stato()['squadre'])} pronte, Support in ascolto.")

    try:
        from segreteria import avvia_telegram
        avvia_telegram(cervello.chiedi)
    except Exception as e:
        print("Segreteria non avviata:", e)

    print(f"\nJarvis {VERSIONE} è pronto. Apri Google Chrome e vai su: http://127.0.0.1:{PORTA}\n")
    # 127.0.0.1 = raggiungibile solo da questo Mac, non dalla rete
    app.run(host="127.0.0.1", port=PORTA, threaded=True)