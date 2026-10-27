# Jarvis 3.2 – Squadre degli agenti, Support e Siti con stili e livelli

Questo pacchetto contiene anche tutto l'aggiornamento 3.1 (stili e livelli dei siti): basta caricare questo.

## Novità 3.2 – Squadre
- **Ogni agente ha una squadra**: un responsabile che riceve l'ordine e operatori con un compito ciascuno.
  Le squadre sono nella nuova cartella `squadre/` (un file .md per squadra): puoi cambiare nomi e compiti senza toccare il codice, poi premi **Ricarica** nella Sala controllo.
- **Squadra Siti web al completo**: Ricercatore → Verificatore → Designer → Sviluppatore → **Revisore qualità** → Copywriter.
  Il Revisore controlla ogni demo (telefono, Chiama, WhatsApp, prezzi inventati, animazioni ammesse dal livello, foto esterne, firma). Se trova problemi la rimanda allo Sviluppatore per **una** correzione; ciò che resta finisce nella scheda dati sotto "Revisione qualità".
- **Coda dei lavori**: puoi chiedere più demo di fila, vanno in coda invece di essere rifiutate.
- **Squadra Support**: il Controllore di sala misura ogni 4 secondi lo stress di ogni squadra (lavori in coda, operatori bloccati da oltre 4 minuti, errori degli ultimi 15 minuti).
  Oltre il 60% manda un **Rinforzo** (fino a 2 per squadra): per i Siti web significa una demo in più in parallelo (massimo 3). Sotto il 25% il rinforzo rientra.
  Il **Riparatore** riprova da solo i lavori falliti per problemi passeggeri (servizio sovraccarico, rete) con attese di 8, 25 e 60 secondi. Vale per Siti, Voli e Blueprint.
- **Sala controllo**: entra nell'universo neurale e tocca l'**astronauta** che galleggia in basso a destra. Vedi tutte le squadre con anello di stress, chi lavora e su cosa, coda, rinforzi, e il registro della Support.
- Costi: le squadre non aggiungono chiamate al modello, tranne la correzione del Revisore quando trova problemi in una demo.

## Novità 3.1 – Siti
- Nel widget Siti web scegli **Stile** (Classico, Futuristico, Cinematografico o "Lascia decidere a Jarvis") e **Livello** (★★★, ★★★★, ★★★★★★).
- Dopo la ricerca Jarvis dà il suo **consiglio di stile**; se è diverso dalla tua scelta compare **"Rifai in stile …"** (senza ripetere la ricerca, la versione precedente resta salvata).
- Regole di stile e livello nella cartella `ispirazioni/`, con la libreria dei 10 riferimenti.
- Skill aggiornate: Demo attività e Preventivo sito (con il listino a stelle).

## File
Cambiati: `siti.py`, `server.py`, `cervello.py`, `interfaccia.html`, `skills/demo-attivita/SKILL.md`, `skills/preventivo-sito/SKILL.md`.
Nuovi: `squadre.py`, cartella `squadre/` (9 file), cartella `ispirazioni/` (5 file), questo file.
Non servono nuove librerie; `.env`, voce, trader e dati restano come sono.

## Caricarlo su GitHub in un nuovo ramo (GitHub Desktop)
1. Apri **GitHub Desktop** e scegli il repository **jarvis3.0**.
2. **Current Branch → New Branch**, scrivi `jarvis-3.2` e premi **Create Branch** (eventuali modifiche lasciale su main).
3. **Repository → Show in Finder** e copia dentro i file e le cartelle di questo pacchetto; quando il Mac chiede, scegli **Sostituisci** (per le cartelle: **Unisci**, non sostituire, così `skills/` mantiene le altre skill).
4. In GitHub Desktop controlla l'elenco dei file cambiati: **non deve esserci `.env`**.
5. Titolo del commit: `Jarvis 3.2: squadre, Support, Sala controllo e siti con stili e livelli`, poi **Commit to jarvis-3.2**.
6. **Publish branch**. Il ramo `main` resta com'era.
7. Se avvii Jarvis da `~/jarvis` e non dalla cartella del repository, copia gli stessi file anche lì.

## Prova
1. Chiudi Jarvis (`Ctrl + C`) e riavvialo con `avvia_jarvis.command`.
2. Nel Terminale: "Squadre: 9 pronte, Support in ascolto." e "Jarvis 3.2 è pronto".
3. Entra nell'universo neurale, tocca l'astronauta: si apre la Sala controllo.
4. Chiedi due demo di fila in Siti web e guarda la Sala controllo: operatori al lavoro, coda, e la Support che manda un rinforzo.
5. Se tutto va bene, su GitHub apri una **Pull request** da `jarvis-3.2` verso `main` e uniscila. Se qualcosa non va, torna a `main` in GitHub Desktop.
