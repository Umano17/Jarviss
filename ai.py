"""Più AI collegate (Jarvis 3.7): Claude resta il cervello, le altre fanno da riserva.

Come funziona:
  - Tutto il codice continua a usare  client.messages.create(...)  e  client.messages.stream(...)  come prima:
    `client()` restituisce un oggetto che si comporta come il client di Anthropic.
  - Se Claude non risponde (credito finito, chiave sbagliata, servizio sovraccarico, rete), la stessa richiesta
    passa alla prima riserva configurata nel .env, nell'ordine di AI_ORDINE (predefinito: openai,gemini,ollama,openrouter).
  - Le riserve parlano il formato «OpenAI compatibile»: OpenAI, Gemini (endpoint compatibile di Google),
    Ollama (AI locale sul Mac) e OpenRouter usano lo stesso adattatore.
  - Gli strumenti di Jarvis (TOOLS) funzionano anche con le riserve. La ricerca web di Claude NO: in riserva
    il modello viene avvisato che non può cercare sul web e non deve inventare fonti.
  - Al primo passaggio a una riserva arriva un avviso su Telegram (al massimo uno ogni ora).
  - Tetto di spesa mensile (TETTO_SPESA_MESE, euro, predefinito 40): avviso al 75%; al 100% le AI a pagamento
    si fermano e restano solo quelle gratuite (Gemini con piano gratuito, Ollama).

Chiavi nel .env (tutte facoltative tranne quella di Claude):
  OPENAI_API_KEY, OPENAI_MODELLO          (predefinito gpt-6-luna)
  GEMINI_API_KEY, GEMINI_MODELLO          (predefinito gemini-3.6-flash)
  OLLAMA_URL, OLLAMA_MODELLO              (predefiniti http://127.0.0.1:11434 e llama3.2)
  OPENROUTER_API_KEY, OPENROUTER_MODELLO  (predefinito openrouter/auto)
  AI_ORDINE=openai,gemini,ollama,openrouter
  TETTO_SPESA_MESE=40
Stato in dati/ai_stato.json (letto dalla schermata). Prova: python ai.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import requests

BASE = Path(__file__).parent
FILE_STATO = BASE / "dati" / "ai_stato.json"
_lock = threading.Lock()

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except Exception:
    pass

AVVISO_RISERVA = ("[Modalità riserva: stai rispondendo al posto di Claude con un'altra AI. La ricerca web non è "
                  "disponibile: non inventare fonti, link, prezzi o notizie; se servono dati aggiornati dillo "
                  "chiaramente. Le regole di Jarvis restano tutte valide.]")

# AI a pagamento: si fermano quando si supera il tetto mensile
A_PAGAMENTO = {"claude", "openai", "openrouter"}

# prezzi indicativi in euro per milione di token (si cambiano nel .env: PREZZO_<AI>_IN / PREZZO_<AI>_OUT)
PREZZI_BASE = {"claude": (2.0, 10.0), "openai": (0.10, 0.50), "gemini": (0.0, 0.0), "ollama": (0.0, 0.0),
               "openrouter": (0.0, 0.0)}


# ---------------------------------------------------------------- configurazione delle riserve

def riserve() -> list[dict]:
    """Riserve configurate, nell'ordine di AI_ORDINE."""
    tutte = {
        "openai": {"url": "https://api.openai.com/v1", "chiave": os.getenv("OPENAI_API_KEY", ""),
                   "modello": os.getenv("OPENAI_MODELLO", "gpt-6-luna"), "token": "max_completion_tokens"},
        "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai",
                   "chiave": os.getenv("GEMINI_API_KEY", ""),
                   "modello": os.getenv("GEMINI_MODELLO", "gemini-3.6-flash"), "token": "max_tokens"},
        "ollama": {"url": os.getenv("OLLAMA_URL", "").rstrip("/") + "/v1" if os.getenv("OLLAMA_URL") else "",
                   "chiave": "ollama", "modello": os.getenv("OLLAMA_MODELLO", "llama3.2"), "token": "max_tokens"},
        "openrouter": {"url": "https://openrouter.ai/api/v1", "chiave": os.getenv("OPENROUTER_API_KEY", ""),
                       "modello": os.getenv("OPENROUTER_MODELLO", "openrouter/auto"), "token": "max_tokens"},
    }
    ordine = [x.strip().lower() for x in os.getenv("AI_ORDINE", "openai,gemini,ollama,openrouter").split(",")]
    out = []
    for nome in ordine:
        r = tutte.get(nome)
        if r and r["url"] and r["chiave"] and "incolla" not in r["chiave"]:
            out.append({"nome": nome, **r})
    return out


# ---------------------------------------------------------------- stato (per schermata e avvisi)

def _leggi_stato() -> dict:
    try:
        d = json.loads(FILE_STATO.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _scrivi_stato(**campi) -> None:
    with _lock:
        d = _leggi_stato()
        d.update(campi)
        try:
            FILE_STATO.parent.mkdir(parents=True, exist_ok=True)
            tmp = FILE_STATO.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, FILE_STATO)
        except OSError:
            pass


def _avvisa(testo: str, chiave: str, ogni_sec: int = 3600) -> None:
    """Avviso su Telegram, al massimo uno ogni ora per lo stesso motivo."""
    st = _leggi_stato()
    ultimi = st.get("avvisi", {})
    if time.time() - ultimi.get(chiave, 0) < ogni_sec:
        return
    ultimi[chiave] = time.time()
    _scrivi_stato(avvisi=ultimi)
    print("AI:", testo)
    try:
        from segreteria import telegram_bot
        if telegram_bot.configurato():
            threading.Thread(target=telegram_bot.notifica, args=(testo,), daemon=True).start()
    except Exception:
        pass


# Claude in pausa dopo un errore di credito/chiave: per qualche minuto si va diretti alla riserva
_pausa_claude = {"fino": 0.0, "motivo": ""}


def stato() -> dict:
    st = _leggi_stato()
    return {"principale": "claude", "riserve": [r["nome"] for r in riserve()],
            "in_uso": st.get("in_uso", "claude"), "ultimo_cambio": st.get("ultimo_cambio", ""),
            "motivo": st.get("motivo", ""), "claude_in_pausa": _pausa_claude["fino"] > time.time() and bool(riserve()),
            "spesa_mese": round(spesa_mese(), 2), "tetto": tetto()}


def _in_uso(nome: str, motivo: str = "") -> None:
    st = _leggi_stato()
    if st.get("in_uso") != nome:
        _scrivi_stato(in_uso=nome, motivo=motivo[:200], ultimo_cambio=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        try:
            import attivita
            attivita.registra("Torno a Claude" if nome == "claude" else f"Passo alla riserva {nome}: {motivo}",
                              "ai", "ok" if nome == "claude" else "avviso")
        except Exception:
            pass
        if nome == "claude":
            _avvisa("Claude risponde di nuovo: torno al cervello principale.", "ritorno")


# ---------------------------------------------------------------- tetto di spesa

def tetto() -> float:
    try:
        return float(os.getenv("TETTO_SPESA_MESE", "40").replace(",", "."))
    except ValueError:
        return 40.0


def _prezzi(nome: str) -> tuple[float, float]:
    base = PREZZI_BASE.get(nome, (0.0, 0.0))
    if nome == "claude":   # se l'utente ha già messo i prezzi di Claude (scheda Uso o .env) valgono quelli
        try:
            import uso
            pi, po = uso._prezzo("PREZZO_INPUT_PER_MILIONE", "prezzoIn"), uso._prezzo("PREZZO_OUTPUT_PER_MILIONE", "prezzoOut")
            base = (pi if pi is not None else base[0], po if po is not None else base[1])
        except Exception:
            pass
    out = []
    for i, suff in enumerate(("IN", "OUT")):
        try:
            out.append(float(os.getenv(f"PREZZO_{nome.upper()}_{suff}", "").replace(",", ".")))
        except ValueError:
            out.append(base[i])
    return out[0], out[1]


def spesa_mese() -> float:
    """Stima della spesa del mese corrente da uso.jsonl (token × prezzi)."""
    try:
        import uso
        inizio = dt.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        tot = 0.0
        with uso._lock:
            righe = uso.FILE.read_text(encoding="utf-8").splitlines() if uso.FILE.exists() else []
        for riga in righe:
            try:
                x = json.loads(riga)
            except ValueError:
                continue
            if x.get("t", 0) < inizio:
                continue
            pi, po = _prezzi(x.get("a", "claude"))
            ingresso = x.get("i", 0) + 1.25 * x.get("cw", 0) + 0.1 * x.get("cr", 0)
            tot += ingresso / 1e6 * pi + x.get("o", 0) / 1e6 * po
        return tot
    except Exception:
        return 0.0


_cache_spesa = {"t": 0.0, "v": 0.0}


def _sopra_tetto() -> bool:
    if time.time() - _cache_spesa["t"] > 300:
        _cache_spesa.update(t=time.time(), v=spesa_mese())
    v, lim = _cache_spesa["v"], tetto()
    if lim <= 0:
        return False
    mese = dt.datetime.now().strftime("%Y-%m")
    if v >= lim * 0.75:
        _avvisa(f"Spesa AI del mese: circa {v:.2f} € su {lim:.0f} € di tetto (75%).", "tetto75-" + mese, 40 * 86400)
    if v >= lim:
        _avvisa(f"Tetto di spesa AI raggiunto ({v:.2f} € su {lim:.0f} €): uso solo le AI gratuite fino al "
                "mese prossimo. Puoi alzarlo con TETTO_SPESA_MESE nel .env.", "tetto100-" + mese, 40 * 86400)
        return True
    return False


# ---------------------------------------------------------------- conversione Anthropic -> OpenAI

def _v(b, k, d=None):
    return b.get(k, d) if isinstance(b, dict) else getattr(b, k, d)


def _testo_system(system) -> str:
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(str(_v(b, "text", "")) for b in system if _v(b, "type") == "text")


def _contenuto_risultato(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(_v(b, "text", "")) for b in c if _v(b, "type") == "text")
    return str(c)


def _messaggi_openai(system, messages) -> list[dict]:
    out = []
    s = _testo_system(system)
    out.append({"role": "system", "content": (s + "\n\n" if s else "") + AVVISO_RISERVA})
    for m in messages:
        ruolo, c = _v(m, "role"), _v(m, "content")
        if isinstance(c, str):
            out.append({"role": ruolo, "content": c})
            continue
        testi, immagini, chiamate, risultati = [], [], [], []
        for b in c or []:
            t = _v(b, "type")
            if t == "text":
                testi.append(str(_v(b, "text", "")))
            elif t == "image":
                src = _v(b, "source", {}) or {}
                if _v(src, "type") == "base64":
                    immagini.append({"type": "image_url", "image_url": {
                        "url": f"data:{_v(src, 'media_type', 'image/jpeg')};base64,{_v(src, 'data', '')}"}})
            elif t == "tool_use":
                chiamate.append({"id": _v(b, "id"), "type": "function", "function": {
                    "name": _v(b, "name"), "arguments": json.dumps(_v(b, "input", {}) or {}, ensure_ascii=False)}})
            elif t == "tool_result":
                risultati.append({"role": "tool", "tool_call_id": _v(b, "tool_use_id"),
                                  "content": _contenuto_risultato(_v(b, "content", ""))})
            # server_tool_use / web_search_tool_result di Claude: non servono alla riserva
        if ruolo == "assistant":
            msg = {"role": "assistant", "content": "\n".join(testi) or None}
            if chiamate:
                msg["tool_calls"] = chiamate
            if msg["content"] or chiamate:
                out.append(msg)
        else:
            out.extend(risultati)          # le risposte degli strumenti vanno subito dopo la chiamata
            if immagini:
                out.append({"role": "user", "content": [{"type": "text", "text": "\n".join(testi)}] + immagini})
            elif testi:
                out.append({"role": "user", "content": "\n".join(testi)})
    return out


def _strumenti_openai(tools) -> list[dict]:
    out = []
    for t in tools or []:
        if _v(t, "input_schema") is None:      # strumenti «di server» di Claude (es. web_search): non disponibili
            continue
        out.append({"type": "function", "function": {"name": _v(t, "name"), "description": _v(t, "description", ""),
                                                     "parameters": _v(t, "input_schema")}})
    return out


def _risposta_anthropic(dati: dict, nome: str, modello: str):
    """Trasforma la risposta OpenAI in un oggetto con la stessa forma di quelle di Claude."""
    scelta = (dati.get("choices") or [{}])[0]
    msg = scelta.get("message") or {}
    blocchi = []
    if msg.get("content"):
        testo = msg["content"] if isinstance(msg["content"], str) else \
            "".join(p.get("text", "") for p in msg["content"] if isinstance(p, dict))
        if testo:
            blocchi.append(SimpleNamespace(type="text", text=testo))
    for c in msg.get("tool_calls") or []:
        f = c.get("function") or {}
        try:
            argomenti = json.loads(f.get("arguments") or "{}")
        except ValueError:
            argomenti = {}
        blocchi.append(SimpleNamespace(type="tool_use", id=c.get("id") or f"riserva_{time.time_ns()}",
                                       name=f.get("name", ""), input=argomenti if isinstance(argomenti, dict) else {}))
    fine = scelta.get("finish_reason")
    stop = "tool_use" if any(b.type == "tool_use" for b in blocchi) else ("max_tokens" if fine == "length" else "end_turn")
    u = dati.get("usage") or {}
    usage = SimpleNamespace(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0),
                            cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None)
    return SimpleNamespace(content=blocchi, stop_reason=stop, usage=usage, model=modello, ai=nome, role="assistant")


def _chiedi_riserva(r: dict, kw: dict):
    corpo = {"model": r["modello"], "messages": _messaggi_openai(kw.get("system"), kw.get("messages", [])),
             r["token"]: int(kw.get("max_tokens", 1500))}
    strumenti = _strumenti_openai(kw.get("tools"))
    if strumenti:
        corpo["tools"] = strumenti
    if "temperature" in kw:
        corpo["temperature"] = kw["temperature"]
    risp = requests.post(f"{r['url']}/chat/completions", json=corpo, timeout=180,
                         headers={"Authorization": f"Bearer {r['chiave']}", "Content-Type": "application/json"})
    if risp.status_code >= 400:
        raise RuntimeError(f"{r['nome']} ha risposto {risp.status_code}: {risp.text[:200]}")
    return _risposta_anthropic(risp.json(), r["nome"], r["modello"])


# ---------------------------------------------------------------- quando passare alla riserva

def _motivo_errore(e: Exception) -> tuple[bool, float, str]:
    """(passare alla riserva?, minuti di pausa per Claude, motivo leggibile)."""
    nome = type(e).__name__
    testo = str(e).lower()
    stato_http = getattr(e, "status_code", None)
    if "credit balance" in testo or "billing" in testo or "credit" in testo and stato_http == 400:
        return True, 30, "credito di Claude esaurito"
    if nome in ("AuthenticationError", "PermissionDeniedError") or stato_http in (401, 403):
        return True, 30, "chiave di Claude non valida"
    if nome == "RateLimitError" or stato_http == 429:
        return True, 2, "Claude ha raggiunto il limite di richieste"
    if nome in ("APIConnectionError", "APITimeoutError", "InternalServerError", "ServiceUnavailableError") or \
            (stato_http or 0) >= 500 or "overloaded" in testo:
        return True, 1, "Claude non raggiungibile o sovraccarico"
    return False, 0, ""


def _con_riserva(kw: dict, errore_claude: Exception | None, motivo: str):
    gratuite_soltanto = _sopra_tetto()
    ultimo = errore_claude
    for r in riserve():
        if gratuite_soltanto and r["nome"] in A_PAGAMENTO:
            continue
        try:
            risposta = _chiedi_riserva(r, kw)
            _in_uso(r["nome"], motivo)
            _avvisa(f"Claude non risponde ({motivo}): sto usando {r['nome']} come riserva. "
                    "La ricerca web resta spenta finché non torna Claude.", "riserva-" + r["nome"])
            return risposta
        except Exception as e:
            print(f"AI: la riserva {r['nome']} non risponde:", repr(e)[:200])
            ultimo = e
    if not riserve():
        _avvisa(f"Claude non risponde ({motivo}) e non c'è nessuna AI di riserva configurata nel .env.", "nessuna")
    raise ultimo or RuntimeError("Nessuna AI disponibile.")


# ---------------------------------------------------------------- il client con riserva

class _Flusso:
    """Si comporta come  client.messages.stream(...)  di Anthropic (text_stream + get_final_message)."""

    def __init__(self, messaggi, kw):
        self._m, self._kw, self._cm, self._s, self._finale = messaggi, kw, None, None, None

    def __enter__(self):
        if self._m._claude_disponibile():
            try:
                self._cm = self._m._vero.stream(**self._kw)
                self._s = self._cm.__enter__()
                _in_uso("claude")
                return self
            except Exception as e:
                passa, pausa, motivo = _motivo_errore(e)
                if not passa:
                    raise
                self._m._pausa(pausa, motivo)
                self._finale = _con_riserva(self._kw, e, motivo)
                return self
        self._finale = _con_riserva(self._kw, None, _pausa_claude["motivo"] or "tetto di spesa")
        return self

    @property
    def text_stream(self):
        if self._s is not None:
            return self._s.text_stream
        return iter([b.text for b in self._finale.content if b.type == "text"])

    def get_final_message(self):
        return self._s.get_final_message() if self._s is not None else self._finale

    def __exit__(self, *a):
        if self._cm is not None:
            return self._cm.__exit__(*a)
        return False


class _Messaggi:
    def __init__(self, vero):
        self._vero = vero

    def _claude_disponibile(self) -> bool:
        if self._vero is None:
            return False
        if _pausa_claude["fino"] > time.time() and riserve():
            return False
        if "claude" in A_PAGAMENTO and _sopra_tetto() and any(r["nome"] not in A_PAGAMENTO for r in riserve()):
            return False
        return True

    def _pausa(self, minuti: float, motivo: str) -> None:
        _pausa_claude.update(fino=time.time() + minuti * 60, motivo=motivo)

    def create(self, **kw):
        if self._claude_disponibile():
            try:
                r = self._vero.create(**kw)
                _in_uso("claude")
                return r
            except Exception as e:
                passa, pausa, motivo = _motivo_errore(e)
                if not passa:
                    raise
                self._pausa(pausa, motivo)
                return _con_riserva(kw, e, motivo)
        return _con_riserva(kw, None, _pausa_claude["motivo"] or "tetto di spesa")

    def stream(self, **kw):
        return _Flusso(self, kw)


class ClientConRiserva:
    def __init__(self, api_key: str | None = None):
        try:
            import anthropic
            vero = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
            self.messages = _Messaggi(vero.messages)
        except Exception as e:      # senza chiave o libreria di Claude: solo riserve
            print("AI: Claude non disponibile all'avvio:", repr(e)[:150])
            self.messages = _Messaggi(None)


def client(api_key: str | None = None) -> ClientConRiserva:
    return ClientConRiserva(api_key)


def prova() -> str:
    """Una domanda breve a ogni AI configurata (dal Terminale: python ai.py)."""
    righe = []
    kw = {"max_tokens": 50, "messages": [{"role": "user", "content": "Rispondi solo: ok"}]}
    for r in riserve():
        try:
            t = "".join(b.text for b in _chiedi_riserva(r, kw).content if b.type == "text")
            righe.append(f"{r['nome']} ({r['modello']}): risponde – {t.strip()[:40]}")
        except Exception as e:
            righe.append(f"{r['nome']} ({r['modello']}): NON risponde – {str(e)[:150]}")
    return "\n".join(righe) or "Nessuna AI di riserva configurata nel .env."


if __name__ == "__main__":
    print(prova())
    print(json.dumps(stato(), ensure_ascii=False, indent=1))
