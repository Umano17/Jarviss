"""Bot Telegram: notifiche sul cellulare e chat con Jarvis."""
import threading, time, requests
from .config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from .agente import gestisci

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def configurato():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID) and "incolla" not in TELEGRAM_TOKEN and "incolla" not in str(TELEGRAM_CHAT_ID)
_avviato = False

def notifica(testo):
    """Manda un messaggio sul tuo cellulare."""
    testo = (testo or "")[:4000]
    if not configurato():
        return
    try:
        requests.post(f"{API}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": testo}, timeout=15)
    except requests.RequestException as e:
        print("Segreteria: Telegram non raggiungibile:", e)

def chiedi_si_no(testo, id_richiesta):
    """Messaggio con i pulsanti SÌ / NO. Restituisce l'id del messaggio (per aggiornarlo con l'esito)."""
    if not configurato():
        return None
    try:
        r = requests.post(f"{API}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID, "text": testo[:4000],
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ SÌ", "callback_data": f"ap:{id_richiesta}:si"},
                {"text": "❌ NO", "callback_data": f"ap:{id_richiesta}:no"}]]}}, timeout=15).json()
        return (r.get("result") or {}).get("message_id")
    except (requests.RequestException, ValueError) as e:
        print("Segreteria: Telegram non raggiungibile:", e)
        return None


def invia_con_pulsanti(testo, pulsanti):
    """Messaggio con pulsanti [(etichetta, dati)] su una riga. Restituisce l'id del messaggio."""
    if not configurato():
        return None
    try:
        r = requests.post(f"{API}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID, "text": testo[:4000],
            "reply_markup": {"inline_keyboard": [[{"text": e, "callback_data": d[:64]} for e, d in pulsanti]]}},
            timeout=15).json()
        return (r.get("result") or {}).get("message_id")
    except (requests.RequestException, ValueError) as e:
        print("Segreteria: Telegram non raggiungibile:", e)
        return None


def invia_foto(percorsi, didascalia=""):
    """Anteprima di immagini (fino a 10) come album; la didascalia va sulla prima."""
    if not configurato() or not percorsi:
        return
    import json as _json
    try:
        percorsi = list(percorsi)[:10]
        if len(percorsi) == 1:
            with open(percorsi[0], "rb") as f:
                requests.post(f"{API}/sendPhoto", data={"chat_id": TELEGRAM_CHAT_ID, "caption": didascalia[:1000]},
                              files={"photo": f}, timeout=60)
            return
        media, files = [], {}
        for i, p in enumerate(percorsi):
            nome = f"foto{i}"
            files[nome] = open(p, "rb")
            media.append({"type": "photo", "media": f"attach://{nome}", **({"caption": didascalia[:1000]} if i == 0 else {})})
        try:
            requests.post(f"{API}/sendMediaGroup", data={"chat_id": TELEGRAM_CHAT_ID, "media": _json.dumps(media)},
                          files=files, timeout=120)
        finally:
            for f in files.values():
                f.close()
    except (requests.RequestException, OSError) as e:
        print("Segreteria: foto non inviate su Telegram:", e)


def modifica_messaggio(message_id, testo):
    """Sostituisce il messaggio della richiesta con l'esito (e toglie i pulsanti)."""
    try:
        requests.post(f"{API}/editMessageText", json={"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id,
                                                      "text": testo[:4000]}, timeout=15)
    except requests.RequestException as e:
        print("Segreteria: Telegram non raggiungibile:", e)


def _pulsante(cb):
    """Pressione di SÌ / NO sotto una richiesta di approvazione."""
    try:
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=10)
    except requests.RequestException:
        pass
    parti = (cb.get("data") or "").split(":")
    if len(parti) != 3 or parti[0] != "ap" or not parti[1].isdigit() or parti[2] not in ("si", "no"):
        return
    try:
        import approvazioni
        approvazioni.decidi(int(parti[1]), parti[2] == "si", "telegram")
    except Exception as e:
        print("Segreteria, approvazione da Telegram:", repr(e))
        notifica("Non sono riuscito a registrare la risposta. Controlla il Terminale sul Mac.")


def _rispondi_a(testo, rispondi_jarvis):
    try:
        import approvazioni
        decisione = approvazioni.risposta_testo(testo, "telegram")
        if decisione is not None:
            if decisione.startswith(("Ci sono più", "Non c'è", "Codice", "Per la richiesta")):
                notifica(decisione)
            return                      # l'esito arriva già nel messaggio della richiesta
    except Exception as e:
        print("Segreteria, approvazioni:", repr(e))
    try:
        risposta = gestisci(testo)
        if risposta is None and rispondi_jarvis:
            risposta = rispondi_jarvis(testo)
    except Exception as e:
        print("Segreteria, errore Telegram:", repr(e))
        risposta = "Si è verificato un errore. Controlla il Terminale sul Mac."
    notifica(risposta or "Non ho una risposta.")

def _comando_jarvis(testo):
    """/aggiorna, /versione, /riavvia (aggiornamenti.py). True se era uno di questi comandi."""
    if not testo.startswith("/"):
        return False
    try:
        import aggiornamenti
        def esegui():
            try:
                r = aggiornamenti.comando_telegram(testo)
            except Exception as e:
                r = f"Errore: {e}"
            if r:
                notifica(r)
        cmd = testo.strip().lower().split("@")[0]
        if cmd in ("/stato", "/spegni", "/accendi"):
            def acceso():
                try:
                    import pannello
                    if cmd == "/stato":
                        import re as _re
                        from pathlib import Path as _P
                        m = _re.search(r'^VERSIONE = "([^"]+)"', (_P(__file__).parent.parent / "server.py").read_text(), _re.M)
                        r = pannello.testo_stato(m.group(1) if m else "")
                    elif cmd == "/spegni":
                        r = pannello.chiedi_spegnimento()
                    else:
                        r = "Jarvis è già acceso. /stato per i dettagli."
                except Exception as e:
                    r = f"Errore: {e}"
                notifica(r)
            threading.Thread(target=acceso, daemon=True).start()
            return True
        if testo.strip().lower().split("@")[0] in ("/aggiorna", "/versione", "/riavvia"):
            threading.Thread(target=esegui, daemon=True).start()
            return True
    except Exception as e:
        print("Aggiornamenti:", repr(e))
    return False


def avvia_telegram(rispondi_jarvis=None):
    """Avvia l'ascolto. rispondi_jarvis = funzione di Jarvis: testo -> risposta (testo)."""
    global _avviato
    if _avviato:
        return
    if not configurato():
        print("Segreteria: Telegram non configurato (servono TELEGRAM_TOKEN e TELEGRAM_CHAT_ID nel file .env).")
        return
    _avviato = True

    def ciclo():
        offset = None
        while True:
            try:
                dati = requests.get(f"{API}/getUpdates",
                                    params={"timeout": 50, "offset": offset},
                                    timeout=60).json()
            except (requests.RequestException, ValueError):
                time.sleep(5)
                continue
            for u in dati.get("result", []):
                offset = u["update_id"] + 1
                cb = u.get("callback_query")
                if cb:
                    if str((cb.get("message") or {}).get("chat", {}).get("id")) == str(TELEGRAM_CHAT_ID) and \
                            str((cb.get("from") or {}).get("id")) == str(TELEGRAM_CHAT_ID):
                        threading.Thread(target=_pulsante, args=(cb,), daemon=True).start()
                    continue   # pulsanti premuti da altri: ignorati
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                    continue   # ignora chiunque non sia tu
                testo = (m.get("text") or "").strip()
                if testo and _comando_jarvis(testo):
                    continue
                if testo:
                    threading.Thread(target=_rispondi_a, args=(testo, rispondi_jarvis),
                                     daemon=True).start()

    threading.Thread(target=ciclo, daemon=True).start()
    print("Segreteria: Telegram attivo.")
    notifica("Jarvis è attivo.")
