"""Prove della zona sacra: quali file Jarvis non può cambiare da solo e quali non accetta mai da un aggiornamento."""
import zona_sacra


def test_file_sacri_riconosciuti_anche_con_percorso_relativo():
    assert zona_sacra.e_sacro("approvazioni.py")
    assert zona_sacra.e_sacro("./server.py")
    assert zona_sacra.e_sacro(" segreteria/telegram_bot.py ")
    assert not zona_sacra.e_sacro("lead_maps.py")
    assert not zona_sacra.e_sacro("segreteria/prova.py")


def test_la_zona_sacra_protegge_se_stessa():
    assert zona_sacra.e_sacro("zona_sacra.py") and zona_sacra.e_sacro(".gitignore")


def test_sacri_toccati_senza_doppioni_e_in_ordine():
    toccati = zona_sacra.sacri_toccati(["siti.py", "server.py", "./server.py", "approvazioni.py"])
    assert toccati == ["./server.py", "approvazioni.py", "server.py"]
    assert zona_sacra.sacri_toccati(["siti.py", "lead_maps.py"]) == []


def test_chiavi_mai_da_un_aggiornamento():
    assert zona_sacra.vietati([".env", "siti.py", "./segreteria/credentials.json"]) == [
        "./segreteria/credentials.json", ".env"]
    assert zona_sacra.vietati(["siti.py", "server.py"]) == []
