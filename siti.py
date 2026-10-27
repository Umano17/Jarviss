"""Jarvis 3.7 – sotto-agente Siti web: demo di sito per attività locali senza sito.

Novità 3.1: tre STILI (classico, futuristico, cinematografico) e tre LIVELLI (★★★, ★★★★, ★★★★★★).
Lo stile si sceglie a mano (o "auto"); dopo la ricerca Jarvis dà il suo consiglio di stile. Le regole di
ogni stile e livello stanno nella cartella ispirazioni/ (file .md modificabili senza toccare il codice).

Novità 3.2: lavora come SQUADRA (squadre/siti.md): Ricercatore, Verificatore, Designer, Sviluppatore, Revisore
qualità (controlli automatici + una correzione), Copywriter. Più demo vanno in coda; con lo stress la Support
manda rinforzi (più demo in parallelo) e il Riparatore riprova i lavori falliti per problemi passeggeri.

Flusso (gira in sottofondo, 1-3 minuti):
  1. RICERCA  – cerca online i dati pubblici dell'attività (solo da fonti trovate, niente invenzioni)
                e controlla se ha già un sito curato: in quel caso si ferma.
  2. COSTRUZIONE – crea un sito dimostrativo in un unico file HTML (bozza, noindex).
  3. CONSEGNA – salva in demo/<nome-attivita>/:
                index.html (la demo), scheda.md (dati + cose da verificare), messaggio.txt (per il titolare),
                dati.json (dati grezzi e fonti).

Si usa dal widget "Siti web" oppure a voce ("prepara una demo per la Pizzeria Da Mario a Bergamo").
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import uso

BASE = Path(__file__).parent
CARTELLA = BASE / "demo"
ISPIRAZIONI = BASE / "ispirazioni"

STILI = {"classico": "Classico", "futuristico": "Futuristico", "cinematografico": "Cinematografico"}
LIVELLI = {"3": "★★★", "4": "★★★★", "6": "★★★★★★"}
MAX_TOKENS_LIVELLO = {"3": 14000, "4": 18000, "6": 26000}

# riserva se i file della cartella ispirazioni/ mancano
GUIDA_STILE_BREVE = {
    "classico": "Elegante e ordinato: colori dai materiali del luogo, serif da titolo con corsivo, foto grandi e poche, "
                "blocco finale a colore pieno con tutte le informazioni pratiche.",
    "futuristico": "Tecnico e modulare: fondo scuro con griglia sottile, un solo accento, monospaziato per etichette e "
                   "numeri, informazioni pratiche come indicatori (anello aperto ora), servizi in riquadri con icone a linea.",
    "cinematografico": "Atmosfera e scene: fondo profondo con luce calda, ogni sezione è una scena, una scena fissa mentre "
                       "il testo scorre, didascalie da inquadratura, barra azioni fissa su telefono.",
}
_lock = threading.Lock()
_lavori: dict[str, dict] = {}          # slug -> stato del lavoro in corso o appena finito

GIORNI = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]

SYSTEM_RICERCA = """Sei l'agente Siti web di Jarvis, fase RICERCA. Ricevi nome e località di un'attività locale.
Cerca sul web (directory, pagine social, siti di settore, Pagine Gialle, TripAdvisor, ecc.) e raccogli SOLO dati
pubblici che trovi davvero nei risultati. Controlla anche se l'attività ha già un proprio sito web.

Rispondi SOLO con un oggetto JSON in questa forma (nessun testo fuori dal JSON):
{"trovata": true,
 "ha_sito": false, "sito": "", "sito_curato": false,
 "nome": "", "categoria": "es. pizzeria, parrucchiere", "indirizzo": "", "citta": "", "telefono": "", "email": "",
 "orari": {"lunedi": "12:00-14:30, 19:00-23:00", "martedi": "chiuso", "mercoledi": "", "giovedi": "", "venerdi": "",
           "sabato": "", "domenica": ""},
 "servizi": ["..."], "specialita": ["..."], "descrizione_breve": "una frase fattuale",
 "social": {"instagram": "", "facebook": ""},
 "stile_suggerito": "colori e atmosfera adatti al tipo di attività, in una frase",
 "stile_consigliato": "classico | futuristico | cinematografico",
 "motivo_stile": "una frase: perché questo stile per questa attività",
 "fonti": [{"nome": "nome del sito", "url": "link"}],
 "conflitti": ["es. telefono diverso tra fonte A e fonte B"],
 "da_verificare": ["dati incerti o mancanti da chiedere al titolare"]}

REGOLE
- Mai inventare: un dato che non trovi resta stringa vuota o lista vuota, e va in da_verificare.
- Orari nel formato HH:MM-HH:MM, più fasce separate da virgola, oppure "chiuso"; vuoto se non noti.
- Se le fonti non concordano, scegli la più recente/ufficiale e segnala il conflitto.
- sito_curato = true solo se il sito trovato è dell'attività, funzionante e fatto con cura (non una pagina
  vuota, un profilo su una directory o un sito di prenotazione generico).
- Se non trovi l'attività, metti trovata=false.
- Gli url delle fonti devono essere copiati esattamente dai risultati di ricerca.
- Nessuna recensione, nessun nome o foto di clienti.
- stile_consigliato: scegli in base a settore, fascia di prezzo, pubblico e atmosfera che emergono dalle fonti.
  classico = tradizione, territorio, famiglia, ospitalità (trattorie, hotel, B&B, cantine, botteghe storiche, studi);
  futuristico = servizi tecnici o moderni, prestazioni e dati (palestre, officine, estetica, tatuatori, informatica,
  barbieri moderni); cinematografico = locali con forte atmosfera serale o d'autore (cocktail bar, ristoranti
  d'autore, locali notturni, lidi la sera). motivo_stile cita un elemento concreto trovato nelle fonti."""

SYSTEM_COSTRUZIONE = """Sei l'agente Siti web di Jarvis, fase COSTRUZIONE. Ricevi i dati verificati di un'attività locale
in JSON e crei una DEMO di sito one-page, moderna e curata, in UN SOLO file HTML (CSS e JS dentro il file).

OBBLIGATORIO
- <meta name="robots" content="noindex, nofollow"> nel <head>; lang="it"; viewport per mobile.
- In cima, una fascia sottile: "Bozza dimostrativa preparata per [nome] – non ufficiale".
- Usa SOLO i dati del JSON. Se un dato manca (telefono, orari, ecc.) scrivi "[da confermare]" o ometti la
  sezione: mai inventare prezzi, piatti, recensioni, anni di attività, premi o persone.
- Niente foto esterne e niente immagini da Google: usa forme, gradienti, icone SVG inline e tipografia.
  Lascia 1-2 riquadri "Qui le vostre foto" eleganti come segnaposto. Sull'elemento che riceverà la foto (un <img> o
  il blocco che la avrà come sfondo) metti data-foto="nome-breve" e data-formato="4:3" (la forma del riquadro),
  così Jarvis potrà inserire e tagliare le foto vere in automatico.
- Sezioni: hero con nome, categoria e pulsanti "Chiama" (tel:), "WhatsApp" e "Indicazioni"
  (https://www.google.com/maps/search/?api=1&query=<nome e indirizzo codificati>); chi siamo (solo dati veri);
  servizi/specialità; orari con stato APERTO/CHIUSO calcolato in JavaScript sull'ora italiana (Europe/Rome);
  contatti e social; piè di pagina con "Demo realizzata da {nome_utente}".
- Dati strutturati JSON-LD schema.org LocalBusiness (o sottotipo adatto) solo con i campi presenti.
- Stile: colori e caratteri presi dal mondo dell'attività (vedi stile_suggerito), un solo elemento memorabile,
  ottimo su telefono, contrasto leggibile (WCAG AA), pulsanti grandi. Caratteri da Google Fonts consentiti.
- Nessuno script esterno, nessun form che invia dati, nessun tracciamento. La demo gira in una "scatola chiusa":
  niente <form action>, niente fetch; i moduli (es. prenotazione) si gestiscono in JavaScript e finiscono in un link.
- WhatsApp: usa https://wa.me/39<numero senza spazi né prefisso> SOLO se il telefono è un cellulare italiano
  (inizia con 3). Altrimenti il pulsante WhatsApp mostra "WhatsApp [da confermare]" e non porta da nessuna parte.
- Menu/listino: usa solo piatti, servizi e prezzi presenti nei dati. Se mancano, mostra la struttura curata del
  menu con 2-3 righe segnaposto "[da confermare]" per categoria: mai prezzi o piatti inventati.
- Rispetta prefers-reduced-motion (niente animazioni se attivo) e il contrasto AA.
- Segui con precisione lo STILE e il LIVELLO indicati sotto: il livello stabilisce quante animazioni e quali
  funzioni sono ammesse (al livello ★★★ nessuna animazione).
Rispondi SOLO con il codice HTML completo, da <!doctype html> a </html>, senza spiegazioni."""


# ---------------------------------------------------------------- stili e livelli

def _leggi(nome: str) -> str:
    try:
        return (ISPIRAZIONI / nome).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def norm_stile(stile) -> str:
    s = str(stile or "").strip().lower()
    return s if s in STILI or s == "auto" else "auto"


def norm_livello(livello) -> str:
    l = str(livello or "").strip().replace("★", "*")
    if l.count("*") in (3, 4, 6):
        return str(l.count("*"))
    return l if l in LIVELLI else "3"


def guida_costruzione(stile: str, livello: str) -> str:
    """Le regole dello stile e del livello, lette dalla cartella ispirazioni/ (con una riserva breve)."""
    g_stile = _leggi(f"stile-{stile}.md") or GUIDA_STILE_BREVE.get(stile, "")
    livelli = _leggi("livelli.md")
    if livelli:
        m = re.search(r"## [★]+ \(livello " + re.escape(livello) + r"\).*?(?=\n## |\Z)", livelli, re.S)
        g_livello = m.group(0) if m else ""
        comuni = re.search(r"## Regole comuni.*", livelli, re.S)
        g_livello += ("\n\n" + comuni.group(0)) if comuni else ""
    else:
        g_livello = f"Livello {LIVELLI.get(livello, livello)}."
    return (f"\n\n=== STILE: {STILI.get(stile, stile).upper()} ===\n{g_stile}"
            f"\n\n=== LIVELLO: {LIVELLI.get(livello, livello)} ===\n{g_livello}")


# ---------------------------------------------------------------- utilità

def slug(testo: str) -> str:
    t = unicodedata.normalize("NFD", str(testo or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:60].strip("-") or "attivita"


def _json_da_testo(testo: str) -> dict:
    m = re.search(r"\{.*\}", testo or "", re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _norm(u: str) -> str:
    return str(u).split("#")[0].split("?utm")[0].rstrip("/").lower()


def _url_dai_risultati(contenuto) -> set[str]:
    trovati = set()
    for b in contenuto:
        if getattr(b, "type", "") != "web_search_tool_result":
            continue
        risultati = getattr(b, "content", None)
        if isinstance(risultati, list):
            for x in risultati:
                u = getattr(x, "url", None) or (x.get("url") if isinstance(x, dict) else None)
                if u:
                    trovati.add(_norm(u))
    return trovati


def _testo(s, n=300) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _lista(v, n=12) -> list[str]:
    return [_testo(x, 120) for x in (v if isinstance(v, list) else []) if _testo(x)][:n]


def pulisci_dati(d: dict, nome: str, citta: str, url_trovati: set[str] | None = None) -> dict:
    """Normalizza i dati della ricerca e scarta le fonti con link non presenti nei risultati."""
    orari_in = d.get("orari") if isinstance(d.get("orari"), dict) else {}
    orari = {}
    for g in GIORNI:
        v = _testo(orari_in.get(g, ""), 60)
        if v and v.lower() != "chiuso" and not re.fullmatch(r"\d{1,2}[:.]\d{2}\s*-\s*\d{1,2}[:.]\d{2}(\s*,\s*\d{1,2}[:.]\d{2}\s*-\s*\d{1,2}[:.]\d{2})*", v):
            v = ""          # formato non riconosciuto: meglio vuoto che sbagliato
        orari[g] = v
    fonti = []
    for f in d.get("fonti", []) if isinstance(d.get("fonti"), list) else []:
        if not isinstance(f, dict):
            continue
        u = str(f.get("url", "")).strip()
        if not u.startswith(("https://", "http://")):
            continue
        if url_trovati and _norm(u) not in url_trovati:
            continue
        fonti.append({"nome": _testo(f.get("nome") or u, 60), "url": u[:500]})
    social = d.get("social") if isinstance(d.get("social"), dict) else {}
    social = {k: str(v).strip()[:300] for k, v in social.items()
              if str(v).strip().startswith(("https://", "http://"))}
    sito = str(d.get("sito", "")).strip()
    return {
        "trovata": d.get("trovata", True) is not False,
        "ha_sito": bool(d.get("ha_sito")) and sito.startswith("http"),
        "sito": sito[:300] if sito.startswith("http") else "",
        "sito_curato": bool(d.get("sito_curato")),
        "nome": _testo(d.get("nome") or nome, 80),
        "categoria": _testo(d.get("categoria"), 60),
        "indirizzo": _testo(d.get("indirizzo"), 160),
        "citta": _testo(d.get("citta") or citta, 60),
        "telefono": _testo(d.get("telefono"), 30),
        "email": _testo(d.get("email"), 80),
        "orari": orari,
        "servizi": _lista(d.get("servizi")),
        "specialita": _lista(d.get("specialita")),
        "descrizione_breve": _testo(d.get("descrizione_breve"), 240),
        "social": social,
        "stile_suggerito": _testo(d.get("stile_suggerito"), 240),
        "stile_consigliato": str(d.get("stile_consigliato", "")).strip().lower() if str(d.get("stile_consigliato", "")).strip().lower() in STILI else "",
        "motivo_stile": _testo(d.get("motivo_stile"), 240),
        "fonti": fonti[:10],
        "conflitti": _lista(d.get("conflitti")),
        "da_verificare": _lista(d.get("da_verificare"), 20),
    }


def controlla_html(html: str, nome: str) -> str:
    """Garanzie minime sulla demo anche se il modello dimentica qualcosa."""
    html = (html or "").strip()
    m = re.search(r"```(?:html)?\s*(.*?)```", html, re.S | re.I)
    if m:
        html = m.group(1).strip()
    i = html.lower().find("<!doctype")
    if i > 0:
        html = html[i:]
    if "<html" not in html.lower():
        raise ValueError("La risposta non contiene una pagina HTML.")
    if not re.search(r'name=["\']robots["\']', html, re.I):
        html = re.sub(r"<head([^>]*)>", r'<head\1>\n<meta name="robots" content="noindex, nofollow">', html, count=1, flags=re.I)
    if "bozza dimostrativa" not in html.lower():
        fascia = ('<div style="background:#111;color:#fff;font:13px/1.4 system-ui,sans-serif;text-align:center;'
                  f'padding:6px 10px">Bozza dimostrativa preparata per {_esc(nome)} – non ufficiale</div>')
        html = re.sub(r"<body([^>]*)>", r"<body\1>" + fascia.replace("\\", "\\\\"), html, count=1, flags=re.I)
    # niente script caricati da fuori
    html = re.sub(r"<script[^>]+src=[\"']https?://[^>]*>\s*</script>", "", html, flags=re.I)
    return html


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def scheda_md(d: dict) -> str:
    r = [f"# Scheda dati – {d['nome']}", "",
         f"Preparata da Jarvis il {dt.date.today():%d/%m/%Y}. Tutto va verificato con il titolare prima di pubblicare.", "",
         "## Dati trovati"]
    for etichetta, k in (("Categoria", "categoria"), ("Indirizzo", "indirizzo"), ("Città", "citta"),
                         ("Telefono", "telefono"), ("Email", "email")):
        r.append(f"- {etichetta}: {d.get(k) or '— da chiedere'}")
    r += ["", "## Orari"]
    for g in GIORNI:
        r.append(f"- {g.capitalize()}: {d['orari'].get(g) or '— da chiedere'}")
    if d["servizi"] or d["specialita"]:
        r += ["", "## Servizi e specialità"] + [f"- {x}" for x in d["servizi"] + d["specialita"]]
    if d["social"]:
        r += ["", "## Social"] + [f"- {k}: {v}" for k, v in d["social"].items()]
    if d.get("stile_consigliato"):
        r += ["", "## Stile consigliato da Jarvis",
              f"- {STILI[d['stile_consigliato']]}: {d.get('motivo_stile') or 'nessun motivo indicato'}"]
    r += ["", "## Da verificare con il titolare"]
    r += [f"- {x}" for x in d["da_verificare"]] or ["- (nessun dubbio segnalato, ma conferma comunque tutto)"]
    r += ["- Permesso scritto per usare foto e logo dai suoi canali", "- Testo \"chi siamo\" e servizi definitivi"]
    if d["conflitti"]:
        r += ["", "## Conflitti tra fonti"] + [f"- {x}" for x in d["conflitti"]]
    r += ["", "## Fonti"] + ([f"- [{f['nome']}]({f['url']})" for f in d["fonti"]] or ["- nessuna fonte verificata"])
    r += ["", "## Prima di pubblicare",
          "- Togliere la fascia \"bozza dimostrativa\" e il meta noindex",
          "- Privacy policy e cookie (se aggiungi mappe o statistiche)",
          "- Collegare il sito alla scheda Google Business Profile dell'attività"]
    return "\n".join(r) + "\n"


def _nome_utente() -> str:
    """Chi firma demo e messaggi: NOME_UTENTE nel file .env."""
    return os.getenv("NOME_UTENTE", "Jonatan").strip() or "Jonatan"


def messaggio_titolare(d: dict) -> str:
    nome = _nome_utente()
    return (f"Buongiorno, sono {nome}. Ho visto che {d['nome']} non ha ancora un sito web e ho preparato, "
            "senza impegno, una bozza di come potrebbe essere: orari sempre aggiornati, tasto per chiamare e "
            "indicazioni per arrivare, tutto pensato per il telefono.\n\n"
            "Ho usato solo informazioni pubbliche, quindi alcuni dati vanno confermati con lei. "
            "Se le interessa, gliela mostro in cinque minuti, di persona o con un link.\n\n"
            f"Grazie e buona giornata,\n{nome}\n")


# ---------------------------------------------------------------- lavoro in sottofondo

def _aggiorna(s: str, **kw):
    with _lock:
        _lavori.setdefault(s, {}).update(kw, agg=time.time())


def _ricerca(client, modello, nome, citta, nota):
    compito = f"Attività: {nome}. Località: {citta}."
    if nota:
        compito += f" Nota: {nota}"
    messaggi = [{"role": "user", "content": compito}]
    trovati, r = set(), None
    for _ in range(6):
        r = client.messages.create(
            model=modello, max_tokens=3000, system=SYSTEM_RICERCA, messages=messaggi,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        )
        uso.registra("siti", r)
        trovati |= _url_dai_risultati(r.content)
        if r.stop_reason != "pause_turn":
            break
        messaggi = [messaggi[0], {"role": "assistant", "content": r.content}]
    testo = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return _json_da_testo(testo), trovati


def _genera_html(client, modello, system, richiesta, livello, max_giri=3):
    """Chiede la pagina e, se il modello si ferma per il limite di lunghezza, gli fa continuare il codice
    esattamente da dove si è interrotto (fino a 3 pezzi). Le demo uscivano tagliate a metà dello script."""
    messaggi = [{"role": "user", "content": richiesta}]
    testo = ""
    for _ in range(max_giri):
        with client.messages.stream(model=modello, max_tokens=MAX_TOKENS_LIVELLO.get(livello, 16000),
                                    system=system, messages=messaggi) as s:
            r = s.get_final_message()
        uso.registra("siti", r)
        pezzo = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        testo += pezzo
        if r.stop_reason != "max_tokens" and "</html>" in testo.lower():
            break
        if r.stop_reason != "max_tokens":
            break      # finito senza </html>: lo segnalerà il Revisore
        messaggi = [messaggi[0], {"role": "assistant", "content": testo},
                    {"role": "user", "content": "La pagina si è interrotta per lunghezza. Continua il codice ESATTAMENTE "
                     "dal carattere in cui si è fermata, senza ripetere nulla e senza spiegazioni, fino a </html>."}]
    return testo


def _costruisci(client, modello, dati, stile="classico", livello="3"):
    pulito = {k: v for k, v in dati.items() if k not in ("fonti", "conflitti", "da_verificare", "ha_sito", "sito_curato",
                                                        "trovata", "stile_consigliato", "motivo_stile")}
    return _genera_html(client, modello, SYSTEM_COSTRUZIONE.replace("{nome_utente}", _nome_utente()) + guida_costruzione(stile, livello),
                        "Dati dell'attività:\n" + json.dumps(pulito, ensure_ascii=False, indent=1), livello)


def revisione(html: str, dati: dict, livello: str) -> list[str]:
    """Il Revisore qualità: controlli automatici sulla pagina (nessun costo, nessuna chiamata al modello)."""
    p, h = [], html.lower()
    testo = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    testo = re.sub(r"<[^>]+>", " ", testo)
    if "</html>" not in h or h.count("<script") > h.count("</script>"):
        p.append("La pagina è INCOMPLETA: si interrompe prima della fine (manca </script> o </html>). Va completata.")
    if 'name="viewport"' not in h and "name='viewport'" not in h:
        p.append("Manca il meta viewport per il telefono.")
    if 'lang="it"' not in h and "lang='it'" not in h:
        p.append('Manca lang="it" sul tag html.')
    cifre = re.sub(r"\D", "", dati.get("telefono", ""))
    if cifre.startswith("39") and len(cifre) > 10:
        cifre = cifre[2:]
    if cifre and "tel:" not in h:
        p.append("Manca il pulsante Chiama con link tel:.")
    for numero in set(re.findall(r"wa\.me/(\d+)", h)):
        if not (cifre.startswith("3") and numero.endswith(cifre)):
            p.append(f"Link WhatsApp wa.me/{numero} non corrisponde a un cellulare dei dati: usa \"WhatsApp [da confermare]\" senza link.")
    if not re.search(r"whatsapp", h):
        p.append("Manca il pulsante WhatsApp.")
    if re.search(r"(?:€\s*\d|\d[\d.,]*\s*€|\d+[.,]\d{2}\s*(?:euro|eur)\b)", testo, re.I):
        p.append("Nella pagina compaiono prezzi, ma i dati dell'attività non ne contengono: sostituiscili con \"[da confermare]\".")
    if re.search(r"<img[^>]+src=[\"']https?://", h) or re.search(r"url\([\"']?https?://(?!fonts\.)", h):
        p.append("Ci sono immagini caricate da siti esterni: usa segnaposto, SVG o gradienti.")
    if re.search(r"<form[^>]+action=", h):
        p.append("C'è un form con action: i moduli vanno gestiti in JavaScript e finire in un link WhatsApp.")
    anim = bool(re.search(r"@keyframes|animation\s*:|intersectionobserver|requestanimationframe", h))
    if livello == "3" and anim:
        p.append("Livello ★★★: la pagina contiene animazioni (keyframes/animation/IntersectionObserver/requestAnimationFrame) da togliere.")
    if livello != "3" and anim and "prefers-reduced-motion" not in h:
        p.append("Le animazioni non rispettano prefers-reduced-motion.")
    if livello in ("4", "6") and cifre.startswith("3") and "wa.me/" not in h:
        p.append("Manca la prenotazione via WhatsApp prevista dal livello.")
    if _nome_utente().lower() not in h:
        p.append(f'Manca "Demo realizzata da {_nome_utente()}" nel piè di pagina.')
    if len(html) > 450_000:
        p.append("La pagina è troppo pesante (oltre 450 KB).")
    return p


SYSTEM_CORREZIONE = """Sei lo Sviluppatore della squadra Siti web di Jarvis. Ricevi una pagina HTML e l'elenco dei problemi
trovati dal Revisore qualità. Correggi SOLO quei problemi, lasciando invariato tutto il resto (stile, testi, struttura).
Rispondi SOLO con il codice HTML completo, da <!doctype html> a </html>, senza spiegazioni."""


def _correggi(client, modello, html, problemi, livello):
    return _genera_html(client, modello, SYSTEM_CORREZIONE,
                        "PROBLEMI DA CORREGGERE:\n- " + "\n- ".join(problemi) + "\n\nPAGINA:\n" + html, livello)


def _dati_salvati(s):
    try:
        d = json.loads((CARTELLA / s / "dati.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("nome") else None
    except (OSError, ValueError):
        return None


def _lavora(s, nome, citta, nota, forza, progetto_id=None, stile="auto", livello="3", riusa=False):
    with uso.per_cliente(demo=s):
        return _lavora_dentro(s, nome, citta, nota, forza, progetto_id, stile, livello, riusa)


def _lavora_dentro(s, nome, citta, nota, forza, progetto_id=None, stile="auto", livello="3", riusa=False):
    import cervello          # import qui: evita il giro cervello -> siti -> cervello
    import squadre

    def T(op, att):
        return squadre.turno("siti", op, att)

    try:
        squadre.nota("siti", f"Nuovo ordine: demo per {nome} ({citta}), stile {stile}, livello {LIVELLI.get(livello, livello)}")
        dati = _dati_salvati(s) if riusa else None
        if dati:
            _aggiorna(s, fase="ricerca", messaggio="Riuso i dati già trovati…")
            squadre.nota("siti", "Riuso i dati già verificati: niente nuova ricerca")
        else:
            _aggiorna(s, fase="ricerca", messaggio="Il Ricercatore cerca i dati pubblici…")
            with T("ricercatore", f"Cerco i dati pubblici di {nome}"):
                grezzi, trovati = squadre.riprova("siti", _ricerca, cervello.client, cervello.MODEL, nome, citta, nota)
            if not grezzi:
                raise ValueError("La ricerca non ha restituito dati leggibili.")
            with T("verificatore", "Pulisco i dati e controllo le fonti"):
                dati = pulisci_dati(grezzi, nome, citta, trovati)
        consigliato = dati.get("stile_consigliato") or ""
        scelto = stile if stile in STILI else (consigliato or "classico")
        cartella = CARTELLA / s
        cartella.mkdir(parents=True, exist_ok=True)
        meta = {"slug": s, "nome": dati["nome"], "citta": dati["citta"], "categoria": dati["categoria"],
                "creata": dt.datetime.now().isoformat(timespec="minutes"), "stato": "", "sito": dati["sito"],
                "stile": scelto, "stile_auto": stile not in STILI, "livello": livello,
                "stile_consigliato": consigliato, "motivo_stile": dati.get("motivo_stile", ""),
                "nota": nota, "forza": bool(forza)}
        (cartella / "dati.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
        if not dati["trovata"]:
            meta["stato"] = "non_trovata"
            (cartella / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            squadre.nota("siti", f"{nome}: attività non trovata, lavoro fermato")
            return _aggiorna(s, fase="non_trovata", messaggio="Non ho trovato l'attività online: controlla nome e città.")
        if dati["ha_sito"] and dati["sito_curato"] and not forza:
            meta["stato"] = "ha_sito"
            (cartella / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            squadre.nota("siti", f"{dati['nome']} ha già un sito curato: lavoro fermato")
            return _aggiorna(s, fase="ha_sito", messaggio=f"Ha già un sito curato: {dati['sito']}. Mi sono fermato.")
        consiglio = ""
        with T("designer", f"Stile {STILI[scelto]} {LIVELLI.get(livello, '')}"):
            if consigliato and consigliato != scelto:
                consiglio = f" Jarvis consiglia lo stile {STILI[consigliato]}: {dati.get('motivo_stile', '')}".rstrip(": ")
            guida_costruzione(scelto, livello)       # verifica che le guide si leggano
        _aggiorna(s, fase="costruzione",
                  messaggio=f"Lo Sviluppatore costruisce la demo {STILI[scelto]} {LIVELLI.get(livello, '')}…" + consiglio)
        with T("sviluppatore", f"Scrivo la pagina di {dati['nome']}"):
            html = controlla_html(squadre.riprova("siti", _costruisci, cervello.client, cervello.MODEL, dati, scelto, livello),
                                  dati["nome"])
        with T("revisore", "Controllo qualità della pagina"):
            problemi = revisione(html, dati, livello)
        if problemi:
            squadre.nota("siti", f"Il Revisore rimanda indietro {len(problemi)} problemi", "revisore")
            _aggiorna(s, fase="costruzione", messaggio=f"Il Revisore ha trovato {len(problemi)} problemi: correzione in corso…")
            try:
                with T("sviluppatore", f"Correggo {len(problemi)} problemi"):
                    corretto = controlla_html(squadre.riprova("siti", _correggi, cervello.client, cervello.MODEL,
                                                              html, problemi, livello), dati["nome"])
                with T("revisore", "Ricontrollo dopo la correzione"):
                    rimasti = revisione(corretto, dati, livello)
                if len(rimasti) <= len(problemi):
                    html, problemi = corretto, rimasti
            except Exception as e:
                print("SITI WEB: correzione non riuscita:", e)
        with T("copywriter", "Scheda dati e messaggio per il titolare"):
            scheda = scheda_md(dati)
            if problemi:
                scheda += "\n## Revisione qualità: da sistemare a mano\n" + "\n".join(f"- {x}" for x in problemi) + "\n"
            (cartella / "scheda.md").write_text(scheda, encoding="utf-8")
            (cartella / "messaggio.txt").write_text(messaggio_titolare(dati), encoding="utf-8")
        (cartella / "index.html").write_text(html, encoding="utf-8")
        # copia per stile e livello: rifacendo la demo in un altro stile la versione precedente non si perde
        (cartella / f"index-{scelto}-{livello}.html").write_text(html, encoding="utf-8")
        meta["stato"] = "pronta"
        meta["da_verificare"] = len(dati["da_verificare"])
        meta["problemi_qualita"] = len(problemi)
        (cartella / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        squadre.nota("siti", f"Demo di {dati['nome']} approvata" + (f" ({len(problemi)} punti da sistemare a mano)" if problemi else ""))
        _aggiorna(s, fase="pronta", messaggio=f"Demo {STILI[scelto]} {LIVELLI.get(livello, '')} pronta." + consiglio)
        if progetto_id:
            try:
                import progetti
                progetti.allega_demo(int(progetto_id), s)
            except Exception as e:
                print("SITI WEB: demo non allegata al progetto:", e)
    except Exception as e:
        print("SITI WEB:", e)
        _aggiorna(s, fase="errore", messaggio="Creazione non riuscita: " + _testo(e, 160))


# ---------------------------------------------------------------- coda dei lavori (la Support aggiunge rinforzi)

_coda: list[dict] = []
_in_corso = 0
_coda_cv = threading.Condition()
_dispatcher = None
MAX_PARALLELO = 3


def _limite() -> int:
    import squadre
    return min(MAX_PARALLELO, 1 + squadre.rinforzi("siti"))


def _segna_coda():
    import squadre
    squadre.segna_coda("siti", len(_coda))


def _esegui(job):
    global _in_corso
    try:
        _lavora(**job)
    finally:
        with _coda_cv:
            _in_corso -= 1
            _coda_cv.notify_all()


def _distributore():
    global _in_corso
    while True:
        with _coda_cv:
            while not _coda or _in_corso >= _limite():
                _coda_cv.wait(timeout=3)
            job = _coda.pop(0)
            _in_corso += 1
            _segna_coda()
        threading.Thread(target=_esegui, args=(job,), daemon=True).start()


def _trova_slug(nome: str, citta: str) -> str | None:
    """Ritrova la cartella di una demo già fatta (il nome trovato online può differire da quello scritto)."""
    n, c = slug(nome), slug(citta)
    for d in elenco():
        if (CARTELLA / d["slug"] / "dati.json").exists() and (
                d["slug"] == slug(f"{nome}-{citta}") or (slug(d.get("nome", "")) == n and slug(d.get("citta", "")) == c)
                or (n and f"-{n}-" in f"-{d['slug']}-" and d["slug"].endswith(c))):
            return d["slug"]
    return None


def crea(nome: str, citta: str, nota: str = "", forza: bool = False, progetto_id=None,
         stile: str = "auto", livello: str = "3", riusa: bool = False) -> dict:
    """Mette in coda la creazione di una demo (lavora in sottofondo).
    forza=True costruisce anche se c'è già un sito; stile: classico, futuristico, cinematografico o auto
    (= quello consigliato dopo la ricerca); livello: 3, 4 o 6 stelle; riusa=True riusa i dati già trovati.
    Più demo insieme vanno in coda: se la squadra è sotto stress la Support manda rinforzi (fino a 3 in parallelo)."""
    global _dispatcher
    nome, citta, nota = _testo(nome, 80), _testo(citta, 60), _testo(nota, 300)
    stile, livello = norm_stile(stile), norm_livello(livello)
    if not nome or not citta:
        return {"errore": "Servono il nome dell'attività e la città."}
    s = slug(f"{nome}-{citta}")
    if riusa and not (CARTELLA / s / "dati.json").exists():
        s = _trova_slug(nome, citta) or s
    with _lock:
        if _lavori.get(s, {}).get("fase") in ("in_coda", "ricerca", "costruzione"):
            return {"errore": f"La demo per {nome} è già in preparazione."}
    with _coda_cv:
        posto = len(_coda) + 1
        _coda.append({"s": s, "nome": nome, "citta": citta, "nota": nota, "forza": forza, "progetto_id": progetto_id,
                      "stile": stile, "livello": livello, "riusa": riusa})
        occupato = _in_corso >= _limite()
        _aggiorna(s, slug=s, nome=nome, citta=citta, fase="in_coda", inizio=time.time(),
                  messaggio=f"In coda (posto {posto})" if occupato else "Avvio…")
        _segna_coda()
        if _dispatcher is None or not _dispatcher.is_alive():
            _dispatcher = threading.Thread(target=_distributore, daemon=True)
            _dispatcher.start()
        _coda_cv.notify_all()
    return {"ok": True, "slug": s, "in_coda": posto if occupato else 0}


def elenco() -> list[dict]:
    """Demo salvate su disco (più recenti prima)."""
    out = []
    if CARTELLA.exists():
        for m in CARTELLA.glob("*/meta.json"):
            try:
                d = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            d["slug"] = m.parent.name
            d["file"] = {f: (m.parent / f).exists() for f in ("index.html", "scheda.md", "messaggio.txt")}
            d["personalizzata"] = (m.parent / "personalizzata" / "index.html").exists()
            try:
                d["link_pubblico"] = json.loads((m.parent / "pubblicazione.json").read_text(encoding="utf-8")).get("url", "")
            except (OSError, ValueError):
                d["link_pubblico"] = ""
            out.append(d)
    return sorted(out, key=lambda d: d.get("creata", ""), reverse=True)[:30]


def stato() -> dict:
    with _lock:
        lavori = sorted(_lavori.values(), key=lambda l: l.get("agg", 0), reverse=True)
        attivi = [dict(l) for l in lavori if l.get("fase") in ("ricerca", "costruzione")]
        in_coda = [dict(l) for l in lavori if l.get("fase") == "in_coda"]
        in_corso = attivi[0] if attivi else (in_coda[0] if in_coda else None)
        ultimo = dict(lavori[0]) if lavori else None
    return {"in_corso": in_corso, "attivi": attivi, "in_coda": in_coda, "ultimo": ultimo, "demo": elenco()}


def testo_per_jarvis() -> str:
    s = stato()
    righe = []
    if s["in_corso"]:
        righe.append(f"In preparazione: {s['in_corso']['nome']} ({s['in_corso']['messaggio']})")
    elif s["ultimo"]:
        righe.append(f"Ultimo lavoro: {s['ultimo']['nome']} – {s['ultimo']['messaggio']}")
    for d in s["demo"][:8]:
        extra = ""
        if d.get("stile"):
            extra = f", stile {STILI.get(d['stile'], d['stile'])} {LIVELLI.get(str(d.get('livello', '')), '')}"
            if d.get("stile_consigliato") and d["stile_consigliato"] != d["stile"]:
                extra += f" (consigliato: {STILI[d['stile_consigliato']]} – {d.get('motivo_stile', '')})"
        righe.append(f"- {d.get('nome')} ({d.get('citta')}): {d.get('stato')}{extra}, creata {d.get('creata', '')[:10]}")
    return "\n".join(righe) or "Nessuna demo creata finora."
