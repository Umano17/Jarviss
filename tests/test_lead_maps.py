"""Prove di lead_maps senza internet e senza spendere: Google è sostituito da risposte finte."""
import pytest

import lead_maps


class Risposta:
    def __init__(self, dati, codice=200):
        self.dati, self.status_code = dati, codice

    def json(self):
        return self.dati


class GoogleFinto:
    """Restituisce le pagine in ordine e ricorda le richieste ricevute."""
    def __init__(self, pagine, codice=200):
        self.pagine, self.codice, self.chiamate = list(pagine), codice, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.chiamate.append(json.copy())
        return Risposta(self.pagine.pop(0) if self.pagine else {"places": []}, self.codice)


def posto(id_, nome, sito="", stelle=4.5, recensioni=50, telefono="0421 123456", stato="OPERATIONAL"):
    return {"id": id_, "displayName": {"text": nome}, "formattedAddress": f"Via Roma {id_}, Jesolo",
            "nationalPhoneNumber": telefono, "websiteUri": sito, "rating": stelle, "userRatingCount": recensioni,
            "googleMapsUri": f"https://maps.google.com/?cid={id_}", "businessStatus": stato,
            "primaryTypeDisplayName": {"text": "Ristorante"}}


class OsmFinto:
    """Finge Overpass: restituisce sempre gli stessi elementi e ricorda le query."""
    def __init__(self, elementi, codice=200):
        self.elementi, self.codice, self.query = elementi, codice, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.query.append(data["data"])
        return Risposta({"elements": self.elementi}, self.codice)


def nodo(id_, nome, sito="", telefono="0421 123456"):
    t = {"name": nome, "addr:street": "Via Roma", "addr:housenumber": id_, "addr:city": "Jesolo"}
    if sito:
        t["website"] = sito
    if telefono:
        t["phone"] = telefono
    return {"type": "node", "id": int(id_), "tags": t}


def test_senza_chiave_usa_openstreetmap_e_verifica_i_siti(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    osm = OsmFinto([nodo("1", "Da Mario"), nodo("2", "Al Faro", sito="https://alfaro.it"),
                    nodo("3", "Pizzeria Luna"), nodo("4", "Trattoria Dubbia")])
    visti = []

    def verificatore(gruppo):
        visti.extend(r["nome"] for r in gruppo)
        return [{"n": 1, "esito": "senza", "url": ""}, {"n": 2, "esito": "sito", "url": "https://luna.it"},
                {"n": 3, "esito": "dubbio", "url": ""}]

    r = lead_maps.cerca("ristoranti", "Jesolo", sito="senza", clienti_esistenti=[], http=osm,
                        verificatore=verificatore)
    assert 'amenity"="restaurant"' in osm.query[0] and 'area["name"="Jesolo"]' in osm.query[0]
    assert visti == ["Da Mario", "Pizzeria Luna", "Trattoria Dubbia"]       # chi ha già il sito non si controlla
    assert [(x["nome"], x["verifica"]) for x in r["righe"]] == [
        ("Da Mario", "senza sito (verificato)"), ("Trattoria Dubbia", "da verificare")]
    assert r["verificate"] == 3 and r["scarti"]["sito"] == 2
    assert "OpenStreetMap" in lead_maps.csv_testo(r)


def test_osm_ignora_stelle_e_categoria_sconosciuta(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    osm = OsmFinto([nodo("1", "Da Mario", sito="https://damario.it")])
    r = lead_maps.cerca("ristoranti", "Jesolo", stelle_min=4, recensioni_min=10, clienti_esistenti=[], http=osm,
                        verificatore=lambda g: [])
    assert [x["nome"] for x in r["righe"]] == ["Da Mario"]
    assert "non disponibile con OpenStreetMap" in lead_maps.csv_testo(r)
    with pytest.raises(RuntimeError) as e:
        lead_maps.cerca("astronavi", "Jesolo", clienti_esistenti=[], http=osm)
    assert "non riconosciuta" in str(e.value)


def test_link_non_trovato_nei_risultati_non_si_accetta(monkeypatch):
    import sys
    import types
    finto = types.SimpleNamespace(
        _norm_url=lambda u: u.rstrip("/").lower(),
        sotto_agente=lambda system, compito, reparto, trovati: (
            trovati.update({"https://vero.it/menu": "https://vero.it/menu"}) or
            '[{"n": 1, "esito": "sito", "url": "https://www.vero.it/"}, {"n": 2, "esito": "sito", "url": "https://inventato.it"}]'))
    monkeypatch.setitem(sys.modules, "cervello", finto)
    nessuna_pagina = type("W", (), {"get": lambda self, url, **k: Risposta(None, 404)})()
    esiti = lead_maps._verifica_con_claude([{"nome": "Alfa", "indirizzo": "x"}, {"nome": "Beta", "indirizzo": "y"}],
                                           http=nessuna_pagina)
    assert esiti[0]["esito"] == "sito" and esiti[1] == {"n": 2, "esito": "dubbio", "url": "", "motivo": "link non confermato"}


def test_pagine_doppioni_clienti_e_filtri(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "finta")
    pagina1 = {"places": [posto("1", "Da Mario"), posto("2", "Al Faro", sito="https://alfaro.it"),
                          posto("3", "Bar Chiuso", stato="CLOSED_PERMANENTLY")], "nextPageToken": "p2"}
    pagina2 = {"places": [posto("1", "Da Mario"), posto("4", "Pizzeria Luna", stelle=3.2),
                          posto("5", "Trattoria Vecchia"), posto("6", "Senza Telefono", telefono="")]}
    g = GoogleFinto([pagina1, pagina2])
    r = lead_maps.cerca("ristoranti", "Jesolo", sito="senza", stelle_min=4, solo_telefono=True,
                        clienti_esistenti=[{"nome": "Trattoria vecchia"}], http=g)
    assert [x["nome"] for x in r["righe"]] == ["Da Mario"]
    assert r["richieste"] == 2 and g.chiamate[1]["pageToken"] == "p2"
    assert r["doppioni"] == 1 and r["gia_clienti"] == 1
    assert r["scarti"] == {"chiuse": 1, "sito": 1, "stelle": 1, "recensioni": 0, "telefono": 1}


def test_limite_e_troppe_combinazioni(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "finta")
    g = GoogleFinto([{"places": [posto(str(i), f"Locale {i}") for i in range(10)]}])
    r = lead_maps.cerca(["bar"], ["Jesolo"], limite=3, clienti_esistenti=[], http=g)
    assert len(r["righe"]) == 3
    r = lead_maps.cerca(["a", "b", "c", "d"], ["x", "y", "z"], clienti_esistenti=[], http=g)
    assert "Troppe combinazioni" in r["errore"]


def test_errore_di_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "finta")
    g = GoogleFinto([{"error": {"message": "API key not valid"}}], codice=400)
    with pytest.raises(RuntimeError) as e:
        lead_maps.cerca("bar", "Jesolo", clienti_esistenti=[], http=g)
    assert "400" in str(e.value) and "API key not valid" in str(e.value)


def test_csv_con_criteri_in_cima(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "finta")
    g = GoogleFinto([{"places": [posto("1", "Da Mario")]}])
    r = lead_maps.cerca("ristoranti, pizzerie", "Jesolo", sito="senza", clienti_esistenti=[], http=g)
    righe = lead_maps.csv_testo(r).splitlines()
    assert righe[0].startswith("CRITERI DELLA RICERCA")
    assert "Categorie,\"ristoranti, pizzerie\"" in righe
    assert "Sito,solo SENZA sito" in righe
    assert righe[-2].startswith("Scelta,Nome,Categoria,Indirizzo")
    assert righe[-1].startswith("FALSE,Da Mario,Ristorante")
    assert "Verifica sito" in righe[-2]


def test_osm_server_sovraccarico_passa_al_successivo(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(lead_maps, "PAUSA_RIPROVA", 0)

    class Instabile(OsmFinto):
        def post(self, url, data=None, headers=None, timeout=None):
            self.query.append(url)
            return Risposta({"elements": self.elementi}, 502 if len(self.query) < 4 else 200)

    osm = Instabile([nodo("1", "Da Mario", sito="https://damario.it")])
    r = lead_maps.cerca("ristoranti", "Jesolo", clienti_esistenti=[], http=osm, verificatore=lambda g: [])
    assert [x["nome"] for x in r["righe"]] == ["Da Mario"] and r["richieste"] == 4
    assert osm.query[:3] == lead_maps.OVERPASS

    sempre_giu = OsmFinto([], codice=504)
    with pytest.raises(RuntimeError) as e:
        lead_maps.cerca("ristoranti", "Jesolo", clienti_esistenti=[], http=sempre_giu)
    assert "sovraccarichi" in str(e.value) and len(sempre_giu.query) == 6


def test_pagina_proposta_aperta_e_controllata(monkeypatch):
    import sys
    import types

    class Web:
        def get(self, url, headers=None, timeout=None):
            pagine = {"https://baladinjesolo.it": "<h1>Baladin Jesolo La Guinguette</h1>",
                      "https://altro.it": "<h1>Un altro locale</h1>"}
            return Risposta(None, 200 if url in pagine else 404) if url not in pagine else type(
                "R", (), {"status_code": 200, "text": pagine[url]})()

    finto = types.SimpleNamespace(sotto_agente=lambda system, compito, reparto, trovati: (
        '[{"n": 1, "esito": "dubbio", "url": "https://baladinjesolo.it"},'
        ' {"n": 2, "esito": "sito", "url": "https://altro.it"}, {"n": 3, "esito": "dubbio", "url": "http://127.0.0.1"}]'))
    monkeypatch.setitem(sys.modules, "cervello", finto)
    lotto = [{"nome": "Baladin Jesolo La Guinguette", "indirizzo": "x"}, {"nome": "Da Mario", "indirizzo": "y"},
             {"nome": "Kiki", "indirizzo": "z"}]
    esiti = lead_maps._verifica_con_claude(lotto, http=Web())
    assert esiti[0]["esito"] == "sito" and esiti[0]["motivo"] == "pagina aperta da Jarvis"
    assert esiti[1]["esito"] == "dubbio" and esiti[1]["url"] == ""      # la pagina non parla di Da Mario
    assert esiti[2]["esito"] == "dubbio" and esiti[2]["url"] == ""      # indirizzi locali mai aperti


def test_categorie_riconosciute():
    assert all(lead_maps.filtri_osm(c) for c in lead_maps.CATEGORIE_ESEMPIO)
    assert lead_maps.filtri_osm("barbieri") == [("shop", "hairdresser")]
    assert lead_maps.filtri_osm("Bar") == [("amenity", "bar"), ("amenity", "cafe")]
    assert lead_maps.filtri_osm("B&B") == [("tourism", "guest_house")]


def test_comune_in_minuscolo_e_nessun_risultato(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    assert lead_maps.nomi_comune("san donà di piave") == ["san donà di piave", "San Donà di Piave"]
    osm = OsmFinto([])
    r = lead_maps.cerca("ristoranti", "thiene", clienti_esistenti=[], http=osm, verificatore=lambda g: [])
    assert 'area["name"="Thiene"]' in osm.query[0] and 'area["name"="thiene"]' in osm.query[0]
    assert "Nessuna attività trovata" in r["errore"]
