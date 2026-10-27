"""Il cervello di Jarvis (versione 3.7): orchestratore + squadre di agenti + skill."""
import os
import subprocess
import datetime as dt
from pathlib import Path

from dotenv import load_dotenv

import ai

import siti
import rubrica
import progetti
import uso
import squadre
import memoria
import impostazioni
from skills_loader import gestore as skill

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")
client = ai.client()   # Claude + riserve (OpenAI, Gemini, Ollama, OpenRouter): vedi ai.py


def crea(reparto, **kw):
    """Chiede al modello e annota quanto è stato usato, per reparto (scheda Uso)."""
    r = client.messages.create(**kw)
    uso.registra(reparto, r)
    return r

# Modelli: restano sulla famiglia 5 (Sonnet 5.5) sia per Jarvis sia per i sotto-agenti.
MODEL = "claude-sonnet-5-5"
MODEL_ORCHESTRATORE = "claude-sonnet-5-5"


# ---------------------------------------------------------------- AGENTE AGENDA (app Calendario del Mac)

def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        return "Errore: " + r.stderr.strip()
    return r.stdout.strip()


def agenda_leggi(giorni=7):
    script = f'''
    set inizio to current date
    set time of inizio to 0
    set fine to inizio + ({int(giorni)} * days)
    set out to ""
    tell application "Calendar"
        repeat with c in calendars
            try
                set evs to (every event of c whose start date >= inizio and start date < fine)
                repeat with e in evs
                    set luogo to ""
                    try
                        set luogo to (location of e)
                        if luogo is missing value then set luogo to ""
                    end try
                    set out to out & (summary of e) & " | " & (start date of e as string) & " | " & (end date of e as string) & " | " & luogo & linefeed
                end repeat
            end try
        end repeat
    end tell
    return out
    '''
    risultato = osa(script)
    return risultato or "Nessun impegno nel periodo richiesto."


def agenda_crea(titolo, inizio_iso, durata_minuti=60):
    import orario
    detta = dt.datetime.fromisoformat(inizio_iso)
    d = orario.al_mac(detta)          # l'ora detta da Jonatan è nel suo fuso; il Calendario del Mac usa quella del Mac
    titolo = titolo.replace('"', "'")
    script = f'''
    set d to current date
    set day of d to 1
    set year of d to {d.year}
    set month of d to {d.month}
    set day of d to {d.day}
    set time of d to {d.hour * 3600 + d.minute * 60}
    tell application "Calendar"
        tell first calendar whose writable is true
            make new event with properties {{summary:"{titolo}", start date:d, end date:d + {int(durata_minuti)} * minutes}}
        end tell
    end tell
    '''
    r = osa(script)
    if r.startswith("Errore"):
        return r
    return f"Evento creato: {titolo}, {detta.strftime('%d/%m/%Y %H:%M')}, {durata_minuti} minuti."


def agenda_cancella(titolo, data_iso):
    """Cancella gli eventi con quel titolo esatto in quella data. Restituisce quanti ne ha cancellati."""
    d = dt.date.fromisoformat(str(data_iso)[:10])
    titolo = titolo.replace('"', "'")
    script = f'''
    set d to current date
    set day of d to 1
    set year of d to {d.year}
    set month of d to {d.month}
    set day of d to {d.day}
    set time of d to 0
    set fine to d + (1 * days)
    set n to 0
    tell application "Calendar"
        repeat with c in calendars
            try
                set evs to (every event of c whose summary is "{titolo}" and start date >= d and start date < fine)
                if (count of evs) > 0 then
                    set n to n + (count of evs)
                    delete (every event of c whose summary is "{titolo}" and start date >= d and start date < fine)
                end if
            end try
        end repeat
    end tell
    return n
    '''
    r = osa(script)
    if r.startswith("Errore"):
        return r
    if r.strip() in ("", "0"):
        return f"Nessun evento chiamato {titolo} il {d.strftime('%d/%m/%Y')}: non ho cancellato nulla."
    return f"Cancellati {r.strip()} eventi: {titolo}, {d.strftime('%d/%m/%Y')}."


# ---------------------------------------------------------------- SOTTO-AGENTI CON RICERCA WEB

SYSTEM_RICERCA = """Sei l'agente di ricerca di Jarvis. Rispondi in italiano.
Regole: cerca sul web, confronta almeno due fonti indipendenti quando possibile,
preferisci fonti primarie (siti ufficiali, documenti, enti). Indica sempre le fonti
con il nome del sito. Se le fonti si contraddicono o non trovi conferme, dillo
chiaramente invece di scegliere a caso. Non inventare nulla. Sii sintetico."""

def _norm_url(u):
    return str(u).split("#")[0].split("?utm")[0].rstrip("/").lower()


def _url_risultati(contenuto):
    out = []
    for b in contenuto:
        if getattr(b, "type", "") != "web_search_tool_result":
            continue
        ris = getattr(b, "content", None)
        if not isinstance(ris, list):
            continue
        for x in ris:
            u = getattr(x, "url", None) or (x.get("url") if isinstance(x, dict) else None)
            if u:
                out.append(str(u))
    return out


def potenza():
    """Manopola Potenza 1-100 (Impostazioni). Il modello resta sempre lo stesso: cambia la profondità."""
    try:
        return max(1, min(100, int(impostazioni.carica().get("potenza", 50))))
    except Exception:
        return 50


def profondita(p=None):
    """(ricerche massime, token di risposta, istruzione extra) per la potenza data."""
    p = potenza() if p is None else p
    if p <= 30:
        return 3, 1500, "Modalità rapida: vai al punto con le fonti essenziali."
    if p <= 70:
        return 5, 2000, ""
    return 9, 3200, ("Modalità massima potenza: confronta almeno tre fonti indipendenti, verifica i numeri due volte "
                     "e segnala ogni dubbio residuo.")


def sotto_agente(system, compito, reparto="ricerca", url_trovati=None):
    ricerche, max_tok, extra = profondita()
    messaggi = [{"role": "user", "content": compito + ("\n\n" + extra if extra else "")}]
    r = None
    for _ in range(6):
        r = crea(reparto,
            model=MODEL,
            max_tokens=max_tok,
            system=sistema_in_cache(system),
            messages=con_cache(messaggi),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": ricerche}],
        )
        if url_trovati is not None:
            url_trovati.update({_norm_url(u): u for u in _url_risultati(r.content)})
        if r.stop_reason != "pause_turn":
            break
        messaggi = [messaggi[0], {"role": "assistant", "content": r.content}]
    return "".join(b.text for b in r.content if b.type == "text")


# ---------------------------------------------------------------- RUBRICA E PROGETTI (strumenti per Jarvis)

def rubrica_cerca(testo):
    r = rubrica.elenco(testo)[:8]
    if not r:
        return "Nessun contatto trovato."
    return "\n".join(f"{c['nome']}" + (f" ({c['attivita']})" if c.get("attivita") else "") + (f", {c['email']}" if c.get("email") else "")
                     + (f", {c['telefono']}" if c.get("telefono") else "") + (" [NON CONTATTARE]" if c.get("non_contattare") else "") for c in r)


def rubrica_aggiungi(nome, email="", telefono="", attivita="", note=""):
    c, err = rubrica.aggiungi({"nome": nome, "email": email, "telefono": telefono, "attivita": attivita, "note": note})
    return ("Non salvato: " + err) if err else f"Contatto salvato: {c['nome']}."


def progetto_crea(nome, tipo="altro", cliente=""):
    cid = None
    if cliente:
        trovati = rubrica.elenco(cliente)
        if len(trovati) == 1:
            cid = trovati[0]["id"]
    p, err = progetti.crea(nome, tipo, cid)
    if err:
        return "Non creato: " + err
    drive = "e su Drive" if p["drive"]["stato"] in ("in_attesa", "in_corso", "ok") else "(Drive non ancora collegato)"
    return f"Progetto «{p['nome']}» creato (#{p['id']}) con la cartella sul Mac {drive}. Agenti collegati: {', '.join(progetti.AGENTI[a] for a in p['agenti'])}."


def progetto_stato(id_):
    md = progetti.leggi_md(int(id_))
    return md or "Progetto non trovato."


def progetto_annota(id_, testo, feedback=False):
    ok = progetti.aggiungi_feedback(int(id_), testo) if feedback else progetti.registra(int(id_), "jarvis", testo)
    return "Annotato nella cartella del progetto." if ok else "Progetto non trovato o testo vuoto."


# ---------------------------------------------------------------- ORCHESTRATORE (Jarvis)

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]
NOME_UTENTE = os.getenv("NOME_UTENTE", "Jonatan").strip() or "Jonatan"


def adesso_roma():
    """Ora attuale nel fuso scelto nelle Impostazioni (orario.py); senza scelta, ora del Mac."""
    import orario
    return orario.adesso()


def system_jarvis():
    import orario
    fuso = orario.descrizione()
    return f"""Sei Jarvis, l'assistente personale di {NOME_UTENTE}. Parli italiano e dai del tu.
Fuso orario: {fuso}. Data e ora attuali sono scritte in fondo a queste istruzioni.

STILE
Professionale, diretto, calmo: un assistente esperto, non un servitore. Rispondi prima con l'informazione
richiesta, poi aggiungi solo ciò che serve. Non scusarti per risposte precedenti: se c'era un errore correggilo
in una frase ("Corretto: ...") e prosegui. Niente formule di cortesia vuote, niente "certamente", "con piacere",
"ottima domanda", niente complimenti, niente domande finali come "posso aiutarti in altro?". Se vedi un rischio
o non sei d'accordo, dillo chiaramente con il motivo.
Le risposte vengono LETTE AD ALTA VOCE: frasi brevi e naturali, niente elenchi, simboli, emoji o markdown.
Massimo 3-4 frasi, salvo quando {NOME_UTENTE} chiede dettagli. Numeri e orari scritti come si dicono.
Se devi usare uno strumento che richiede qualche secondo (ricerca, lead, notizie), prima di usarlo
di' una frase brevissima come "Controllo subito."

VERITÀ E FONTI
Per notizie, prezzi e fatti recenti usa la ricerca online (strumento ricerca o notizie_giorno) e cita la
fonte in breve, per nome. Se un dato non è verificabile dillo chiaramente. Non inventare mai.

AGENDA
Usa agenda_leggi. Quando riassumi gli impegni di': ora, titolo e luogo (se c'è). Segnala le sovrapposizioni
tra impegni. Per creare (agenda_crea) o cancellare (agenda_cancella) un evento usa direttamente lo strumento: parte
una richiesta SÌ/NO su Telegram e sullo schermo e l'evento cambia solo dopo il sì di {NOME_UTENTE}. Se mancano
titolo, data o ora, chiedili prima.

ALTRI STRUMENTI
Notizie del giorno: notizie_giorno (sono anche nel riquadro Notizie con i
link agli articoli).
Briefing della giornata: leggi agenda di oggi e le due o tre notizie più importanti, poi riassumi tutto in
5-6 frasi brevi.

SITI WEB PER ATTIVITÀ LOCALI
Per preparare la demo di un sito usa sito_demo_crea con nome dell'attività e città (chiedili se mancano). Servono
anche lo STILE (classico, futuristico, cinematografico, oppure auto = lo sceglie Jarvis dopo la ricerca) e il
LIVELLO (3 stelle: bello e scorrevole, menu curato non animato; 4 stelle: prenotazione WhatsApp e menu scorrevole;
6 stelle: ultrapregiato e interattivo). Se {NOME_UTENTE} non li dice, chiedili in una sola domanda; se risponde
"decidi tu" usa stile auto e livello 3. Lavora in sottofondo per un paio di minuti: di' che è partita e che la trova
nel riquadro Siti web. Dopo la ricerca Jarvis dà il suo consiglio di stile: se è diverso dalla scelta, riferiscilo
in una frase con il motivo; per rifare la demo nello stile consigliato usa sito_demo_crea con riusa=true (non
ripete la ricerca). Per sapere a che punto è o quali demo esistono usa siti_demo_elenco. Mai dati inventati; la
demo non va pubblicata senza il sì del titolare.

PRODUTTIVITÀ (i servizi che {NOME_UTENTE} vende)
Squadre: Commerciale (clienti in pipeline e richiami), Contenuti, Testi su richiesta, SEO locale, Amministrazione
(listino, preventivi, abbonamenti, incassi), più Siti web. Per sapere come va il lavoro usa
produttivita_stato. Nuovi lead: lead_cerca trova attività sulle mappe (Google Maps se c'è la chiave, altrimenti
OpenStreetMap con i siti mancanti verificati sul web) per categoria, località e criteri (per esempio "ristoranti a
Jesolo senza sito") e salva il foglio su Drive; chiedi categoria e località
se mancano, poi riferisci quante ne ha tenute e dove trovarle. Clienti: cliente_aggiungi, clienti_elenco, cliente_aggiorna (stato: trovato, demo, contattato,
risposta, trattativa, cliente, perso; quando diventa "contattato" il richiamo a 3 giorni si mette da solo).
messaggio_cliente PREPARA un testo per WhatsApp, email o telefonata: non lo invia mai; leggilo a {NOME_UTENTE}.
Contenuti: contenuto_crea (anche per un cliente) e contenuti_ricorrenti per le bozze automatiche di ogni mese.
Testi su richiesta: lavoro_crea dal brief, lavoro_rivedi con le correzioni. SEO locale: seo_locale (ricerca
online, un paio di minuti). Preventivi: leggi prima listino, poi preventivo_crea con gli id delle voci; i prezzi
"da decidere" vanno scelti da {NOME_UTENTE} (listino_prezzo) prima di inviare. preventivo_stato per inviato,
accettato, pagato o rifiutato: accettato crea gli abbonamenti mensili, pagato registra l'incasso. Incassi e
margine: incassi_riepilogo. Pubblicare una demo online (sito_pubblica) è un'azione verso l'esterno: solo se
{NOME_UTENTE} lo chiede esplicitamente. Mai prezzi, fatti o dati del cliente inventati.

MEMORIA
Quando {NOME_UTENTE} dice "ricordati", "tieni a mente", "salva che" o ti dà una regola stabile, usa memoria_salva
(categoria: istruzione per le regole sempre valide, business, listino, stile, cliente, altro). Le note pertinenti
ti arrivano già in fondo alle istruzioni; per cercarne altre usa memoria_cerca. Non salvare dati sensibili
(salute, documenti, password, numeri di carte).

PROGETTI E RUBRICA
Ogni progetto (sito web, ricerca, altro) ha una cartella sul Mac e su Drive con un file progetto.md
condiviso dagli agenti. Prima di lavorare su un progetto leggi progetto_stato; quando finisci annota con
progetto_annota cosa hai fatto; un feedback dato da {NOME_UTENTE} o dal cliente va registrato con feedback=true.
Non cancellare e non sovrascrivere nulla nella cartella: aggiungi file nuovi. Per creare un progetto usa
progetto_crea (chiedi nome e tipo se mancano). La rubrica si legge con rubrica_cerca e si completa con
rubrica_aggiungi. Non scrivere mai email a un contatto segnato NON CONTATTARE.

APPROVAZIONI
Le azioni critiche (creare o cancellare eventi, pubblicare una demo, inviare
un'email, interventi del Manutentore) non partono subito: lo strumento manda a {NOME_UTENTE} una richiesta con i
pulsanti SÌ e NO su Telegram e nella coda «Da approvare» sullo schermo. Funziona anche quando non è al Mac. Dopo
aver usato uno di questi strumenti di' solo che hai mandato la richiesta; non chiedere conferma in chat e non dire
che l'azione è fatta. Tu non puoi approvare nulla: decide sempre lui.

COMPORTAMENTO GENERALE
Se una richiesta è ambigua, fai una sola domanda breve. Le azioni irreversibili o a pagamento passano sempre da
una richiesta di approvazione."""


def adesso_testo():
    n = adesso_roma()
    return f"{GIORNI[n.weekday()]} {n.day} {MESI[n.month - 1]} {n.year}, ore {n:%H:%M}"


CACHE = {"type": "ephemeral"}


def system_completo(domanda=""):
    """Prompt diviso in due: la parte fissa resta in cache (più veloce e costa circa un decimo),
    la parte che cambia (ora, skill attiva, note di memoria pertinenti) viene dopo e non rompe la cache."""
    extra = skill.contesto_per_modello()
    mem = memoria.contesto(domanda)
    variabile = ("Adesso è " + adesso_testo() + "." + ("\n\n" + mem if mem else "") +
                 ("\n\n" + extra if extra else ""))
    return [{"type": "text", "text": system_jarvis(), "cache_control": CACHE},
            {"type": "text", "text": variabile}]


def con_cache(messaggi):
    """Copia dei messaggi con il segnalibro di cache sull'ultimo blocco: nei giri con strumenti
    la conversazione già vista non viene ripagata per intero."""
    if not messaggi:
        return messaggi
    out = list(messaggi[:-1])
    ultimo = dict(messaggi[-1])
    c = ultimo["content"]
    if isinstance(c, str):
        c = [{"type": "text", "text": c}]
    c = [dict(x) if isinstance(x, dict) else x for x in c]
    if c and isinstance(c[-1], dict):
        c[-1]["cache_control"] = CACHE
    ultimo["content"] = c
    out.append(ultimo)
    return out


def sistema_in_cache(testo):
    """Prompt fisso di un sotto-agente come blocco in cache."""
    return [{"type": "text", "text": testo, "cache_control": CACHE}]

TOOLS = [
    {
        "name": "agenda_leggi",
        "description": "Legge gli impegni in calendario per i prossimi N giorni (oggi incluso).",
        "input_schema": {
            "type": "object",
            "properties": {"giorni": {"type": "integer", "description": "Quanti giorni guardare, default 7"}},
        },
    },
    {
        "name": "agenda_crea",
        "description": "Chiede l'approvazione (SÌ/NO su Telegram) e poi crea un evento nel calendario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titolo": {"type": "string"},
                "inizio_iso": {"type": "string", "description": "Data e ora di inizio, formato 2026-10-05T15:30"},
                "durata_minuti": {"type": "integer"},
            },
            "required": ["titolo", "inizio_iso"],
        },
    },
    {
        "name": "agenda_cancella",
        "description": "Chiede l'approvazione (SÌ/NO su Telegram) e poi cancella dal calendario gli eventi con questo titolo esatto in questa data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titolo": {"type": "string", "description": "Titolo esatto dell'evento, come lo legge agenda_leggi"},
                "data_iso": {"type": "string", "description": "Data dell'evento, formato 2026-10-05"},
            },
            "required": ["titolo", "data_iso"],
        },
    },
    {
        "name": "ricerca",
        "description": "Cerca informazioni online e risponde con fonti verificate e incrociate.",
        "input_schema": {
            "type": "object",
            "properties": {"domanda": {"type": "string"}},
            "required": ["domanda"],
        },
    },
    {
        "name": "notizie_giorno",
        "description": "Le notizie più importanti di oggi (Italia, mondo, economia, tecnologia) con la fonte.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "skill_attiva",
        "description": "Attiva una skill (procedura scritta) tra quelle elencate nella sezione SKILL. Restituisce le istruzioni da seguire.",
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string", "description": "Nome esatto della skill, es. demo-attivita"}},
            "required": ["nome"],
        },
    },
    {
        "name": "skill_disattiva",
        "description": "Disattiva la skill attiva quando il compito è finito o l'utente cambia argomento.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "sito_demo_crea",
        "description": "Avvia in sottofondo la creazione della demo di sito per un'attività locale: ricerca dati pubblici, controllo se ha già un sito, pagina demo, scheda dati e messaggio per il titolare.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome dell'attività"},
                "citta": {"type": "string", "description": "Città o località"},
                "nota": {"type": "string", "description": "Indicazioni facoltative (stile, servizi da mettere in evidenza)"},
                "forza": {"type": "boolean", "description": "true = crea la demo anche se l'attività ha già un sito. Solo se l'utente lo chiede."},
                "stile": {"type": "string", "enum": ["auto", "classico", "futuristico", "cinematografico"],
                          "description": "Stile della demo. auto = quello consigliato da Jarvis dopo la ricerca. Default auto."},
                "livello": {"type": "string", "enum": ["3", "4", "6"],
                            "description": "Livello di offerta in stelle: 3, 4 o 6. Default 3."},
                "riusa": {"type": "boolean", "description": "true = riusa i dati già trovati per questa attività (per rifare la demo in un altro stile o livello senza nuova ricerca)."},
                "progetto_id": {"type": "integer", "description": "Facoltativo: numero del progetto sito a cui allegare la demo (cartella 02 Demo)."},
            },
            "required": ["nome", "citta"],
        },
    },
    {
        "name": "sito_foto",
        "description": "Inserisce le foto vere nella demo personalizzata di un sito: prende le foto dalla cartella demo/<slug>/foto-da-inserire, le raddrizza, le taglia nella forma di ogni riquadro, le comprime e le mette al loro posto. Con solo_elenco=true mostra solo gli spazi foto e quali foto ci andrebbero.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Nome della cartella della demo, es. salicornia-jesolo (o il nome dell'attività)"},
                "solo_elenco": {"type": "boolean", "description": "true = non modifica nulla, elenca spazi e foto"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "siti_demo_elenco",
        "description": "Stato della demo in preparazione e elenco delle demo di siti già create.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "rubrica_cerca",
        "description": "Cerca nella rubrica (nome, attività o email). Restituisce email, telefono e se il contatto è segnato NON CONTATTARE.",
        "input_schema": {"type": "object", "properties": {"testo": {"type": "string"}}, "required": ["testo"]},
    },
    {
        "name": "rubrica_aggiungi",
        "description": "Aggiunge un contatto alla rubrica.",
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string"}, "email": {"type": "string"}, "telefono": {"type": "string"},
                           "attivita": {"type": "string"}, "note": {"type": "string"}},
            "required": ["nome"],
        },
    },
    {
        "name": "progetto_crea",
        "description": "Crea un progetto con la sua cartella (sul Mac e su Google Drive) e il file progetto.md condiviso dagli agenti. Tipi: sito, ricerca, altro.",
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string"}, "tipo": {"type": "string", "enum": ["sito", "ricerca", "altro"]},
                           "cliente": {"type": "string", "description": "Nome del contatto in rubrica, facoltativo"}},
            "required": ["nome", "tipo"],
        },
    },
    {
        "name": "progetti_elenco",
        "description": "Elenca i progetti con il loro numero (id), tipo, agenti collegati e feedback.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "progetto_stato",
        "description": "Legge il file progetto.md di un progetto (stato condiviso: registro e feedback). Leggilo PRIMA di lavorare su un progetto.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    {
        "name": "progetto_annota",
        "description": "Aggiunge una riga al registro del progetto (cosa hai fatto) oppure, con feedback=true, registra un feedback dato dall'utente o dal cliente.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "testo": {"type": "string"}, "feedback": {"type": "boolean"}},
            "required": ["id", "testo"],
        },
    },
    # ---------------- PRODUTTIVITÀ (3.5)
    {"name": "produttivita_stato", "description": "Come va il lavoro: clienti per stato, richiami di oggi, incassi del mese, canoni mensili, preventivi aperti, bozze da approvare.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "clienti_elenco", "description": "Elenco dei clienti con numero (#id), stato e richiamo. Facoltativo: filtra per stato.",
     "input_schema": {"type": "object", "properties": {"stato": {"type": "string", "enum": ["", "trovato", "demo", "contattato", "risposta", "trattativa", "cliente", "perso"]}}}},
    {"name": "cliente_aggiungi", "description": "Aggiunge un cliente o un'attività da contattare alla pipeline.",
     "input_schema": {"type": "object", "properties": {
         "nome": {"type": "string"}, "citta": {"type": "string"}, "categoria": {"type": "string"},
         "telefono": {"type": "string"}, "email": {"type": "string"}, "note": {"type": "string"},
         "stato": {"type": "string", "enum": ["trovato", "demo", "contattato", "risposta", "trattativa", "cliente"]}},
         "required": ["nome"]}},
    {"name": "cliente_aggiorna", "description": "Aggiorna un cliente: stato nella pipeline, nota nella sua storia, data del prossimo richiamo (AAAA-MM-GG), telefono, email, link della demo pubblicata. richiamo_fatto=true se Jonatan l'ha richiamato e non ha ancora deciso.",
     "input_schema": {"type": "object", "properties": {
         "cliente": {"type": "string", "description": "Nome o numero del cliente"},
         "stato": {"type": "string", "enum": ["trovato", "demo", "contattato", "risposta", "trattativa", "cliente", "perso"]},
         "nota": {"type": "string"}, "richiamo": {"type": "string"}, "richiamo_fatto": {"type": "boolean"},
         "telefono": {"type": "string"}, "email": {"type": "string"}, "link_demo": {"type": "string"}},
         "required": ["cliente"]}},
    {"name": "messaggio_cliente", "description": "PREPARA (non invia) un messaggio per un cliente: primo contatto, richiamo, risposta a chi è interessato o accompagnamento al preventivo. Canale whatsapp, email o telefono (traccia per la chiamata).",
     "input_schema": {"type": "object", "properties": {
         "cliente": {"type": "string"}, "tipo": {"type": "string", "enum": ["primo", "richiamo", "risposta", "preventivo"]},
         "canale": {"type": "string", "enum": ["whatsapp", "email", "telefono"]}, "nota": {"type": "string"}},
         "required": ["cliente"]}},
    {"name": "contenuto_crea", "description": "Crea la bozza di un contenuto: Post social, Post LinkedIn, Newsletter, Articolo SEO, Thread X, Script video, Descrizione Google Business. Anche per un cliente.",
     "input_schema": {"type": "object", "properties": {
         "tipo": {"type": "string", "enum": ["Post social", "Post LinkedIn", "Newsletter", "Articolo SEO", "Thread X", "Script video", "Descrizione Google Business"]},
         "argomento": {"type": "string"}, "cliente": {"type": "string", "description": "Facoltativo: nome o numero del cliente"},
         "nota": {"type": "string"}}, "required": ["tipo", "argomento"]}},
    {"name": "contenuti_ricorrenti", "description": "Imposta bozze automatiche ogni mese per un cliente (es. 4 post il giorno 1). Le bozze restano da approvare: nulla viene pubblicato.",
     "input_schema": {"type": "object", "properties": {
         "cliente": {"type": "string"}, "tipo": {"type": "string", "enum": ["Post social", "Post LinkedIn", "Newsletter", "Articolo SEO", "Thread X", "Script video"]},
         "quantita": {"type": "integer"}, "giorno": {"type": "integer", "description": "Giorno del mese, 1-28"},
         "guida": {"type": "string", "description": "Temi o indicazioni per i contenuti"}}, "required": ["cliente", "tipo"]}},
    {"name": "lavoro_crea", "description": "Testi su richiesta: dal brief crea la bozza di un lavoro (Ghostwriting, Riscrittura, Traduzione, Testi per sito, Proposta di consulenza, Script di vendita).",
     "input_schema": {"type": "object", "properties": {
         "servizio": {"type": "string", "enum": ["Ghostwriting", "Riscrittura", "Traduzione", "Testi per sito", "Proposta di consulenza", "Script di vendita"]},
         "titolo": {"type": "string"}, "brief": {"type": "string"}, "cliente": {"type": "string"}}, "required": ["servizio", "brief"]}},
    {"name": "lavoro_rivedi", "description": "Nuova versione di un lavoro su richiesta applicando le correzioni.",
     "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}, "correzioni": {"type": "string"}}, "required": ["id", "correzioni"]}},
    {"name": "seo_locale", "description": "Agente SEO locale: controlla online scheda Google, coerenza di nome-indirizzo-telefono, sito e directory di un'attività e propone i 3 interventi più utili. Richiede un paio di minuti.",
     "input_schema": {"type": "object", "properties": {"nome": {"type": "string"}, "citta": {"type": "string"}, "cliente": {"type": "string"}}}},
    {"name": "lead_cerca", "description": "Lead da Maps: cerca sulle mappe (Google Places API se c'è la chiave, altrimenti OpenStreetMap con verifica web dei siti mancanti) le attività di una o più categorie in una o più località, toglie doppioni e clienti già presenti, applica i filtri e salva un Foglio Google su Drive (cartella Jarvis/Lead) con i criteri in cima. Le nuove attività entrano nei clienti come trovato. Non dà email.",
     "input_schema": {"type": "object", "properties": {
         "categorie": {"type": "string", "description": "Una o più, separate da virgola (es. ristoranti, pizzerie)"},
         "localita": {"type": "string", "description": "Comuni o province, separati da virgola"},
         "limite": {"type": "integer", "description": "Quante attività al massimo, default 60, massimo 200"},
         "sito": {"type": "string", "enum": ["tutti", "senza", "con"], "description": "senza = solo attività senza sito"},
         "stelle_min": {"type": "number"}, "recensioni_min": {"type": "integer"},
         "solo_telefono": {"type": "boolean"}, "nei_clienti": {"type": "boolean", "description": "Default true"}},
         "required": ["categorie", "localita"]}},
    {"name": "listino", "description": "Legge il listino dei servizi con gli id delle voci e i prezzi (IVA esclusa; alcuni da decidere).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "listino_prezzo", "description": "Imposta il prezzo di una voce del listino (solo quando Jonatan dice il prezzo).",
     "input_schema": {"type": "object", "properties": {"voce": {"type": "string", "description": "id della voce"}, "prezzo": {"type": "number"}}, "required": ["voce", "prezzo"]}},
    {"name": "preventivo_crea", "description": "Crea un preventivo per un cliente con voci del listino (id). Il cliente passa in trattativa.",
     "input_schema": {"type": "object", "properties": {
         "cliente": {"type": "string"}, "voci": {"type": "array", "items": {"type": "string"}}, "note": {"type": "string"}},
         "required": ["cliente", "voci"]}},
    {"name": "preventivo_stato", "description": "Cambia lo stato di un preventivo (inviato, accettato, pagato, rifiutato) o aggiunge il link di pagamento. Accettato crea gli abbonamenti; pagato registra l'incasso.",
     "input_schema": {"type": "object", "properties": {
         "numero": {"type": "string", "description": "Numero del preventivo, es. 2026-001"},
         "stato": {"type": "string", "enum": ["inviato", "accettato", "pagato", "rifiutato"]},
         "link_pagamento": {"type": "string"}}, "required": ["numero"]}},
    {"name": "incassi_riepilogo", "description": "Incassi del mese e degli ultimi mesi, canoni mensili attivi e da incassare, margine per cliente (incassato contro costo dell'AI).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "sito_pubblica", "description": "Chiede l'approvazione (SÌ/NO su Telegram) e poi pubblica online la demo di un sito (versione personalizzata se c'è) per avere un link da mandare al titolare. Solo su richiesta esplicita.",
     "input_schema": {"type": "object", "properties": {"slug": {"type": "string", "description": "Cartella della demo o nome dell'attività"}}, "required": ["slug"]}},
    {"name": "memoria_salva", "description": "Salva una nota permanente nella memoria di Jarvis.",
     "input_schema": {"type": "object", "properties": {
         "titolo": {"type": "string"}, "testo": {"type": "string"},
         "categoria": {"type": "string", "enum": ["istruzione", "business", "listino", "stile", "cliente", "altro"]}},
         "required": ["testo", "categoria"]}},
    {"name": "memoria_cerca", "description": "Cerca nelle note salvate in memoria.",
     "input_schema": {"type": "object", "properties": {"domanda": {"type": "string"}}, "required": ["domanda"]}}
]

ETICHETTE = {
    "agenda_leggi": "Consulto l'agenda...",
    "agenda_crea": "Chiedo il tuo sì per l'evento...",
    "agenda_cancella": "Chiedo il tuo sì per cancellare...",
    "ricerca": "Cerco online e verifico le fonti...",
    "notizie_giorno": "Leggo le notizie del giorno...",
    "skill_attiva": "Attivo la skill...",
    "skill_disattiva": "Chiudo la skill...",
    "sito_demo_crea": "Avvio la demo del sito...",
    "produttivita_stato": "Guardo come va il lavoro...",
    "clienti_elenco": "Apro i clienti...",
    "cliente_aggiungi": "Aggiungo il cliente...",
    "cliente_aggiorna": "Aggiorno il cliente...",
    "messaggio_cliente": "Preparo il messaggio...",
    "contenuto_crea": "Scrivo il contenuto...",
    "contenuti_ricorrenti": "Imposto i contenuti del mese...",
    "lavoro_crea": "Preparo la bozza...",
    "lavoro_rivedi": "Applico le correzioni...",
    "seo_locale": "Controllo la presenza su Google...",
    "lead_cerca": "Cerco le attività sulle mappe...",
    "listino": "Apro il listino...",
    "listino_prezzo": "Aggiorno il listino...",
    "preventivo_crea": "Preparo il preventivo...",
    "preventivo_stato": "Aggiorno il preventivo...",
    "incassi_riepilogo": "Guardo gli incassi...",
    "sito_pubblica": "Pubblico la demo...",
    "memoria_salva": "Me lo segno...",
    "memoria_cerca": "Cerco nella memoria...",
    "sito_foto": "Sistemo le foto nella demo...",
    "siti_demo_elenco": "Controllo le demo dei siti...",
    "rubrica_cerca": "Cerco in rubrica...",
    "rubrica_aggiungi": "Salvo il contatto...",
    "progetto_crea": "Creo il progetto e la cartella...",
    "progetti_elenco": "Controllo i progetti...",
    "progetto_stato": "Leggo la cartella del progetto...",
    "progetto_annota": "Annoto nel progetto...",
}


def esegui_tool(nome, a):
    try:
        if nome == "agenda_leggi":
            return agenda_leggi(a.get("giorni", 7))
        if nome == "agenda_crea":
            return _chiedi("agenda_crea", {"titolo": a["titolo"], "inizio_iso": a["inizio_iso"],
                                           "durata_minuti": a.get("durata_minuti", 60)},
                           f"Creare l'evento «{a['titolo']}» il {a['inizio_iso'].replace('T', ' alle ')[:19]} "
                           f"({a.get('durata_minuti', 60)} minuti) nel Calendario?")
        if nome == "agenda_cancella":
            return _chiedi("agenda_cancella", {"titolo": a["titolo"], "data_iso": a["data_iso"]},
                           f"Cancellare dal Calendario l'evento «{a['titolo']}» del {a['data_iso'][:10]}?")
        if nome == "ricerca":
            return sotto_agente(SYSTEM_RICERCA, a["domanda"])
        if nome == "rubrica_cerca":
            return rubrica_cerca(a["testo"])
        if nome == "rubrica_aggiungi":
            return rubrica_aggiungi(a["nome"], a.get("email", ""), a.get("telefono", ""), a.get("attivita", ""), a.get("note", ""))
        if nome == "progetto_crea":
            return progetto_crea(a["nome"], a.get("tipo", "altro"), a.get("cliente", ""))
        if nome == "progetti_elenco":
            return progetti.testo_per_jarvis()
        if nome == "progetto_stato":
            return progetto_stato(a["id"])
        if nome == "progetto_annota":
            return progetto_annota(a["id"], a["testo"], bool(a.get("feedback", False)))
        if nome == "notizie_giorno":
            import notizie_giorno
            return notizie_giorno.testo_per_jarvis()
        if nome == "skill_attiva":
            s = skill.attiva(a["nome"])
            return f"Skill {s['nome']} attiva. Istruzioni:\n{s['istruzioni']}" + (
                "\nLe azioni che modificano file o dati passano da una richiesta di approvazione SÌ/NO." if s["conferma"] else "")
        if nome == "skill_disattiva":
            skill.disattiva()
            return "Nessuna skill attiva."
        if nome == "sito_demo_crea":
            r = siti.crea(a.get("nome", ""), a.get("citta", ""), a.get("nota", ""), bool(a.get("forza", False)),
                          a.get("progetto_id"), stile=a.get("stile", "auto"), livello=a.get("livello", "3"),
                          riusa=bool(a.get("riusa", False)))
            if r.get("errore"):
                return r["errore"]
            return ("Demo avviata in sottofondo: pronta in un paio di minuti nel riquadro Siti web. "
                    "A fine lavoro siti_demo_elenco riporta anche lo stile consigliato.")
        if nome == "siti_demo_elenco":
            return siti.testo_per_jarvis()
        if nome in STRUMENTI_PRODUTTIVITA:
            return _esegui_produttivita(nome, a)
        if nome == "sito_foto":
            import foto_sito
            slug = siti.slug(a.get("slug") or a.get("nome", ""))
            r = foto_sito.applica(slug, solo_elenco=bool(a.get("solo_elenco", False)))
            testo = foto_sito.testo_per_jarvis(r)
            if not r.get("errore") and not a.get("solo_elenco"):
                testo += f" Anteprima: http://127.0.0.1:8765/demo/{slug}/personalizzata/"
            return testo
        return "Strumento sconosciuto."
    except Exception as e:
        return f"Errore nello strumento {nome}: {e}"


_storia = []


def azzera():
    global _storia
    _storia = []


def chiedi_stream(testo):
    """Risponde a pezzetti: la schermata può cominciare a parlare dopo la prima frase."""
    global _storia
    messaggi = _storia + [{"role": "user", "content": testo}]
    totale = ""
    primo_giro = True
    while True:
        if not primo_giro:
            totale += " "
            yield {"tipo": "testo", "testo": " "}
        primo_giro = False
        with client.messages.stream(
            model=MODEL_ORCHESTRATORE,
            max_tokens=1500,
            system=system_completo(testo),
            tools=TOOLS,
            messages=con_cache(messaggi),
        ) as s:
            for pezzo in s.text_stream:
                totale += pezzo
                yield {"tipo": "testo", "testo": pezzo}
            r = s.get_final_message()
        uso.registra("jarvis", r)
        messaggi.append({"role": "assistant", "content": r.content})
        if r.stop_reason != "tool_use":
            break
        risultati = []
        for b in r.content:
            if b.type == "tool_use":
                print(f"  [Jarvis usa: {b.name}]")
                yield {"tipo": "stato", "testo": ETICHETTE.get(b.name, "Un attimo...")}
                try:
                    with squadre.per_strumento(b.name):
                        out = esegui_tool(b.name, b.input)
                except Exception as e:          # esegui_tool gestisce già i suoi errori: qui solo per sicurezza
                    out = f"Errore nello strumento {b.name}: {e}"
                risultati.append({"type": "tool_result", "tool_use_id": b.id, "content": str(out)})
        messaggi.append({"role": "user", "content": risultati})

    risposta = totale.strip() or "Fatto."
    _storia += [{"role": "user", "content": testo}, {"role": "assistant", "content": risposta}]
    _storia = _storia[-20:]


def chiedi(testo):
    """Versione senza streaming (usata come riserva)."""
    return "".join(e["testo"] for e in chiedi_stream(testo) if e["tipo"] == "testo").strip() or "Fatto."


# ---------------------------------------------------------------- PRODUTTIVITÀ: esecuzione degli strumenti

STRUMENTI_PRODUTTIVITA = {"produttivita_stato", "clienti_elenco", "cliente_aggiungi", "cliente_aggiorna",
                          "messaggio_cliente", "contenuto_crea", "contenuti_ricorrenti", "lavoro_crea", "lavoro_rivedi",
                          "seo_locale", "lead_cerca", "listino", "listino_prezzo", "preventivo_crea", "preventivo_stato",
                          "incassi_riepilogo", "sito_pubblica", "memoria_salva", "memoria_cerca"}


def _cli(a, chiave="cliente"):
    import produttivita as P
    v = a.get(chiave)
    if v in (None, ""):
        return None, ""
    c = P.trova_cliente(str(v))
    if not c:
        return None, f"Non trovo il cliente «{v}»: usa clienti_elenco per il nome esatto o il numero."
    return c, ""


def _esegui_produttivita(nome, a):
    import produttivita as P
    if nome == "produttivita_stato":
        return P.testo_per_jarvis()
    if nome == "clienti_elenco":
        P.sincronizza_demo()
        return P.elenco_clienti_testo(a.get("stato", ""))
    if nome == "cliente_aggiungi":
        c, err = P.aggiungi_cliente(a.get("nome"), a.get("citta", ""), a.get("categoria", ""), a.get("telefono", ""),
                                    a.get("email", ""), a.get("note", ""), a.get("stato", "trovato"))
        return err or f"Cliente #{c['id']} {c['nome']} aggiunto in stato {dict(P.STATI_CLIENTE)[c['stato']]}."
    if nome == "cliente_aggiorna":
        c, err = _cli(a)
        if err or not c:
            return err or "Dimmi quale cliente."
        if a.get("richiamo_fatto"):
            c, err = P.richiamo_fatto(c["id"], a.get("nota", ""))
        else:
            c, err = P.aggiorna_cliente(c["id"], stato=a.get("stato"), nota=a.get("nota"), richiamo=a.get("richiamo"),
                                        telefono=a.get("telefono"), email=a.get("email"), link_demo=a.get("link_demo"))
        if err:
            return err
        return (f"{c['nome']}: {dict(P.STATI_CLIENTE)[c['stato']]}" +
                (f", prossimo richiamo il {c['richiamo']}" if c.get("richiamo") else ", nessun richiamo in programma") + ".")
    if nome == "messaggio_cliente":
        c, err = _cli(a)
        if err or not c:
            return err or "Dimmi per quale cliente."
        r = P.prepara_messaggio(c["id"], a.get("tipo", "primo"), a.get("canale", "whatsapp"), a.get("nota", ""))
        return r.get("errore") or ("Messaggio preparato (NON inviato), da leggere a Jonatan:\n" + r["testo"])
    if nome == "contenuto_crea":
        c, err = _cli(a)
        if err:
            return err
        x = P.crea_contenuto(a.get("tipo"), a.get("argomento"), c["id"] if c else None, a.get("nota", ""))
        return x.get("errore") or f"Bozza #{x['id']} ({x['tipo']}) pronta nella scheda Produttività, da approvare:\n{x['testo']}"
    if nome == "contenuti_ricorrenti":
        c, err = _cli(a)
        if err or not c:
            return err or "Dimmi per quale cliente."
        r, err = P.crea_ricorrente(c["id"], a.get("tipo"), a.get("quantita", 4), a.get("giorno", 1), a.get("guida", ""))
        return err or f"Ogni mese, dal giorno {r['giorno']}, preparo {r['quantita']} bozze di {r['tipo']} per {r['cliente']}. Restano da approvare."
    if nome == "lavoro_crea":
        c, err = _cli(a)
        if err:
            return err
        x = P.crea_lavoro(a.get("servizio"), a.get("titolo", ""), a.get("brief", ""), c["id"] if c else None)
        return x.get("errore") or f"Lavoro #{x['id']} in bozza nella scheda Produttività:\n{x['versioni'][-1]['testo']}"
    if nome == "lavoro_rivedi":
        x = P.rivedi_lavoro(a.get("id"), a.get("correzioni", ""))
        return x.get("errore") or f"Versione {len(x['versioni'])} del lavoro #{x['id']} pronta:\n{x['versioni'][-1]['testo']}"
    if nome == "lead_cerca":
        import lead_maps
        try:
            ris = lead_maps.cerca(a.get("categorie"), a.get("localita"), a.get("limite", 60), a.get("sito", "tutti"),
                                  a.get("stelle_min", 0), a.get("recensioni_min", 0), bool(a.get("solo_telefono")))
        except RuntimeError as e:
            return str(e)
        if "errore" in ris:
            return ris["errore"]
        return lead_maps.testo_per_jarvis(ris, lead_maps.salva(ris, nei_clienti=a.get("nei_clienti", True) is not False))
    if nome == "seo_locale":
        import seo_locale
        c, err = _cli(a)
        if err:
            return err
        r = seo_locale.analizza(a.get("nome", ""), a.get("citta", ""), c["id"] if c else None)
        return r.get("errore") or f"Rapporto SEO salvato ({r['file']}).\n{r['testo']}"
    if nome == "listino":
        return P.testo_listino()
    if nome == "listino_prezzo":
        v, err = P.aggiorna_voce(a.get("voce"), prezzo=a.get("prezzo"))
        return err or f"{v['nome']}: ora {P._euro(v['prezzo'])}" + ("" if v["unita"] == "una tantum" else f" / {v['unita']}") + "."
    if nome == "preventivo_crea":
        c, err = _cli(a)
        if err or not c:
            return err or "Dimmi per quale cliente."
        p, err = P.crea_preventivo(c["id"], a.get("voci", []), a.get("note", ""))
        if err:
            return err
        return (f"Preventivo {p['numero']} per {p['cliente']}: una tantum {P._euro(p['una_tantum'])}" +
                (f", canone {P._euro(p['mensile'])} al mese" if p["mensile"] else "") +
                (". Attenzione: ci sono prezzi da decidere, completali prima di inviarlo." if p["da_decidere"] else ". È in bozza nella scheda Produttività."))
    if nome == "preventivo_stato":
        p = next((x for x in P.preventivi() if x["numero"] == str(a.get("numero", "")).strip()), None)
        if not p:
            return "Preventivo non trovato."
        p, err = P.aggiorna_preventivo(p["id"], stato=a.get("stato"), link_pagamento=a.get("link_pagamento"))
        return err or f"Preventivo {p['numero']}: {p['stato']}."
    if nome == "incassi_riepilogo":
        k = P.cassa()
        m = P.margine()
        r = [f"Incassato questo mese: {P._euro(k['incassato_mese'])}. Canoni mensili attivi: {P._euro(k['mrr'])} ({k['abbonamenti_attivi']})."]
        if k["abbonamenti_da_incassare"]:
            r.append("Da incassare questo mese: " + ", ".join(f"{x['cliente']} {P._euro(x['prezzo_mese'])}" for x in k["abbonamenti_da_incassare"]) + ".")
        r.append(f"Preventivi aperti: {k['preventivi_aperti']} per {P._euro(k['valore_preventivi_aperti'])}.")
        for x in m[:6]:
            r.append(f"{x['cliente']}: incassato {P._euro(x['incassato'])}, costo AI " +
                     (P._euro(x['costo_ai']) if x["costo_ai"] is not None else f"{x['token']} token (prezzi non impostati)") + ".")
        return " ".join(r)
    if nome == "sito_pubblica":
        s = siti.slug(a.get("slug", ""))
        if not (siti.CARTELLA / s).is_dir():
            return "Demo non trovata: usa siti_demo_elenco per il nome giusto."
        return _chiedi("sito_pubblica", {"slug": s}, f"Pubblicare online la demo «{s}» (bozza non indicizzata)? "
                       "Chiunque abbia il link potrà vederla.", chiave=f"pubblica:{s}")
    if nome == "memoria_salva":
        n, err = memoria.salva(a.get("titolo", ""), a.get("testo", ""), a.get("categoria", "altro"))
        return err or f"Salvato in memoria ({n['categoria']}): {n['titolo']}."
    if nome == "memoria_cerca":
        return memoria.testo_per_jarvis(memoria.cerca(a.get("domanda", ""), 8, escludi_istruzioni=False))
    return "Strumento sconosciuto."


# ---------------------------------------------------------------- APPROVAZIONI (SÌ / NO su Telegram e sullo schermo)

def _chiedi(azione, argomenti, descrizione, chiave=""):
    import approvazioni
    try:
        r = approvazioni.richiedi(azione, argomenti, descrizione, chiave=chiave)
    except Exception as e:
        return f"Non riesco a creare la richiesta di approvazione: {e}"
    from segreteria import configurato
    dove = "su Telegram e sullo schermo" if configurato() else "sullo schermo (Telegram non è collegato)"
    return (f"Richiesta n.{r['id']} mandata {dove}: aspetto il SÌ o il NO di {NOME_UTENTE}. "
            "Non è ancora fatto.")


def _pubblica_dopo_si(slug):
    import pubblica
    r = pubblica.pubblica(slug)
    if r.get("errore"):
        raise RuntimeError(r["errore"])
    return f"Demo pubblicata: {r['url']}" if r["modo"] == "netlify" else r["istruzioni"]


def _registra_approvazioni():
    import approvazioni
    approvazioni.registra("agenda_crea", lambda titolo, inizio_iso, durata_minuti=60: agenda_crea(titolo, inizio_iso, durata_minuti))
    approvazioni.registra("agenda_cancella", lambda titolo, data_iso: agenda_cancella(titolo, data_iso))
    approvazioni.registra("sito_pubblica", _pubblica_dopo_si)


_registra_approvazioni()
