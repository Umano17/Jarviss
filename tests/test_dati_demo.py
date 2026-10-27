"""Prove dei dati demo e della firma dei messaggi, in una cartella temporanea: i dati veri non si toccano."""
import json

import pytest

import attivita
import crea_dati_demo
import lead_maps
import memoria
import produttivita
import siti


@pytest.fixture
def dati(tmp_path, monkeypatch):
    """Sposta in una cartella temporanea tutti i file che lo script scrive."""
    d = tmp_path / "dati"
    monkeypatch.setattr(crea_dati_demo, "DATI", d)
    monkeypatch.setattr(produttivita, "DATI", d)
    monkeypatch.setattr(memoria, "FILE", d / "memoria.json")
    monkeypatch.setattr(attivita, "FILE", d / "attivita.jsonl")
    monkeypatch.setattr(lead_maps, "BASE", tmp_path)
    monkeypatch.setattr(lead_maps, "CARTELLA", d / "lead")
    monkeypatch.setattr(lead_maps, "STORICO", d / "lead" / "ricerche.json")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "non-usare")
    return d


def test_crea_dati_demo(dati):
    testo = crea_dati_demo.crea()
    assert "5 lead" in testo
    clienti = {c["nome"]: c["stato"] for c in json.loads((dati / "clienti.json").read_text(encoding="utf-8"))}
    assert clienti["Pizzeria Luna"] == "demo" and clienti["Da Nino al Porto"] == "cliente"
    assert "Osteria del Faro" not in clienti                 # ha già il sito: non è un lead
    storico = json.loads((dati / "lead" / "ricerche.json").read_text(encoding="utf-8"))
    assert storico[0]["fonte"] == "osm" and storico[0]["link"] == ""   # mappa finta, niente Drive
    assert len(memoria.elenco()) == 3
    assert produttivita.preventivi()[0]["stato"] == "accettato"


def test_non_tocca_dati_esistenti(dati):
    dati.mkdir()
    (dati / "clienti.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit):
        crea_dati_demo.crea()
    assert (dati / "clienti.json").read_text(encoding="utf-8") == "[]"


def test_firma_dal_file_env(monkeypatch):
    monkeypatch.setenv("NOME_UTENTE", "Giulia")
    assert "sono Giulia" in siti.messaggio_titolare({"nome": "Pizzeria Luna"})
    problemi = siti.revisione("<html><footer>Demo realizzata da Giulia</footer></html>", {}, "3")
    assert not any("piè di pagina" in p for p in problemi)
