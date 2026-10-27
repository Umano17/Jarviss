"""Prove delle approvazioni senza Telegram vero: il bot è finto e i dati vanno in una cartella temporanea."""
import re
import time

import pytest

import approvazioni


class BotFinto:
    """Finge il bot Telegram: ricorda i messaggi, così si legge il codice di verifica mandato."""
    def __init__(self):
        self.messaggi, self.modifiche = [], []

    def chiedi_si_no(self, testo, id_):
        self.messaggi.append(testo)
        return 100 + id_

    def notifica(self, testo):
        self.messaggi.append(testo)

    def modifica_messaggio(self, mid, testo):
        self.modifiche.append((mid, testo))

    def ultimo_codice(self):
        return re.findall(r"Codice di verifica[^:]*: (\d{6})", "\n".join(self.messaggi))[-1]


@pytest.fixture
def ap(tmp_path, monkeypatch):
    """Approvazioni isolate: file temporaneo, bot finto, azioni registrate solo per il test."""
    bot = BotFinto()
    monkeypatch.setattr(approvazioni, "FILE", tmp_path / "approvazioni.json")
    monkeypatch.setattr(approvazioni, "_tg", lambda: bot)
    monkeypatch.setattr(approvazioni, "_diario", lambda *a, **k: None)
    monkeypatch.setattr(approvazioni, "_AZIONI", {})
    monkeypatch.setattr(approvazioni, "_RIFIUTO", {})
    eseguite, rifiutate = [], []
    approvazioni.registra("pubblica", lambda nome: eseguite.append(nome) or f"Pubblicata {nome}.",
                          al_rifiuto=lambda nome: rifiutate.append(nome))
    approvazioni.bot, approvazioni.eseguite, approvazioni.rifiutate = bot, eseguite, rifiutate
    return approvazioni


def stato(ap, id_):
    return next(a["stato"] for a in ap._leggi() if a["id"] == id_)


def test_azione_non_registrata_non_si_puo_chiedere(ap):
    with pytest.raises(ValueError):
        ap.richiedi("cancella_tutto", {}, "Cancello tutto?")


def test_si_esegue_e_no_annulla(ap):
    a = ap.richiedi("pubblica", {"nome": "Da Mario"}, "Pubblico la demo di Da Mario?")
    assert a["id"] == 1 and "serve il tuo sì" in ap.bot.messaggi[0]
    assert ap.decidi(1, True) == "Pubblicata Da Mario."
    assert ap.eseguite == ["Da Mario"] and stato(ap, 1) == "approvata"
    assert "già approvata" in ap.decidi(1, True)               # una seconda volta non riparte
    assert ap.eseguite == ["Da Mario"]

    ap.richiedi("pubblica", {"nome": "Al Faro"}, "Pubblico la demo di Al Faro?")
    assert ap.decidi(2, False).startswith("Annullato")
    assert ap.rifiutate == ["Al Faro"] and stato(ap, 2) == "rifiutata"
    assert ap.eseguite == ["Da Mario"]


def test_stessa_chiave_non_crea_doppioni(ap):
    a = ap.richiedi("pubblica", {"nome": "Da Mario"}, "Pubblico?", chiave="demo-1")
    b = ap.richiedi("pubblica", {"nome": "Da Mario"}, "Pubblico?", chiave="demo-1")
    assert a["id"] == b["id"] and len(ap.in_attesa()) == 1


def test_azione_che_fallisce_finisce_in_errore(ap):
    def rotta(nome):
        raise RuntimeError("Netlify non risponde")
    ap.registra("rotta", rotta)
    ap.richiedi("rotta", {"nome": "x"}, "Provo?")
    assert "non è riuscita" in ap.decidi(1, True) and stato(ap, 1) == "errore"


def test_risposte_scritte(ap):
    assert ap.risposta_testo("sì", "telegram") is None          # niente in attesa: non è una risposta
    ap.richiedi("pubblica", {"nome": "Da Mario"}, "Pubblico?")
    assert ap.risposta_testo("ciao Jarvis", "telegram") is None
    assert ap.risposta_testo("Sì!", "telegram") == "Pubblicata Da Mario."

    ap.richiedi("pubblica", {"nome": "A"}, "Pubblico A?")
    ap.richiedi("pubblica", {"nome": "B"}, "Pubblico B?")
    assert "più richieste in attesa" in ap.risposta_testo("ok", "telegram")   # due aperte: serve il numero
    assert "nessuna richiesta n.9" in ap.risposta_testo("sì 9", "telegram")
    assert ap.risposta_testo("no n. 3", "telegram").startswith("Annullato")
    assert ap.rifiutate == ["B"] and stato(ap, 2) == "in_attesa"


def test_richiesta_senza_risposta_scade(ap):
    ap.richiedi("pubblica", {"nome": "Da Mario"}, "Pubblico?", scadenza_ore=-1)
    assert ap.in_attesa() == []
    assert stato(ap, 1) == "scaduta" and ap.rifiutate == ["Da Mario"] and ap.eseguite == []


def test_zona_sacra_serve_il_codice(ap):
    ap.richiedi("pubblica", {"nome": "server.py"}, "Aggiorno server.py?", sacra=True)
    assert "ZONA SACRA" in ap.bot.messaggi[0]
    assert "codice di verifica" in ap.decidi(1, True)
    assert ap.eseguite == [] and stato(ap, 1) == "attesa_codice"
    codice = ap.bot.ultimo_codice()
    assert codice not in ap.FILE.read_text(encoding="utf-8")   # il codice non si salva in chiaro
    assert "aspetto il codice" in ap.decidi(1, True)           # un altro SÌ non basta

    assert ap.risposta_testo(f"{codice[:3]} {codice[3:]}", "telegram") == "Pubblicata server.py."
    assert ap.eseguite == ["server.py"]
    assert "nessuna richiesta" in ap.verifica_codice(1, codice)  # vale una volta sola


def test_zona_sacra_tre_codici_sbagliati_annullano(ap):
    ap.richiedi("pubblica", {"nome": "server.py"}, "Aggiorno server.py?", sacra=True)
    ap.decidi(1, True)
    giusto = ap.bot.ultimo_codice()
    sbagliato = f"{(int(giusto) + 1) % 10 ** 6:06d}"
    assert "Tentativi rimasti: 2" in ap.verifica_codice(1, sbagliato)
    assert "Tentativi rimasti: 1" in ap.verifica_codice(1, "12")     # troppo corto: conta come sbagliato
    assert "terza volta" in ap.verifica_codice(1, sbagliato)
    assert stato(ap, 1) == "annullata" and ap.rifiutate == ["server.py"]
    assert "nessuna richiesta" in ap.verifica_codice(1, giusto)      # dopo l'annullamento il giusto non vale più
    assert ap.eseguite == []


def test_zona_sacra_codice_scaduto(ap, monkeypatch):
    ap.richiedi("pubblica", {"nome": "server.py"}, "Aggiorno server.py?", sacra=True)
    ap.decidi(1, True)
    codice = ap.bot.ultimo_codice()
    adesso = time.time()
    monkeypatch.setattr(ap.time, "time", lambda: adesso + ap.CODICE_MINUTI * 60 + 1)
    assert "nessuna richiesta" in ap.verifica_codice(1, codice)
    assert stato(ap, 1) == "annullata" and ap.eseguite == []


def test_zona_sacra_senza_telegram_non_fa_nulla(ap, monkeypatch):
    monkeypatch.setattr(ap, "_tg", lambda: None)
    ap.richiedi("pubblica", {"nome": "server.py"}, "Aggiorno server.py?", sacra=True)
    assert "Non ho fatto nulla" in ap.decidi(1, True)
    assert ap.eseguite == [] and stato(ap, 1) == "in_attesa"
