# Jarvis 3.5 – Reparto Produttività

Un nuovo reparto nella barra in alto (e un nuovo nodo dorato nella sfera): **Produttività**, dove stanno i
servizi che vendi e tutto quello che serve per farti pagare. Le idee buone dell'armatura (contenuti, testi su
richiesta, memoria, manopola potenza) sono state riscritte dentro Jarvis; React, MongoDB, chiave Emergent e
crediti finti sono rimasti fuori.

## Le 9 sezioni della scheda Produttività
- **Panoramica**: incassato del mese, canoni mensili attivi, preventivi aperti, pipeline, chi richiamare oggi, cose da fare.
- **Clienti**: lavagna a colonne Trovato → Demo pronta → Contattato → Ha risposto → Trattativa → Cliente / Perso.
  Le demo pronte di Siti web entrano da sole. Quando segni «Contattato» Jarvis fissa il richiamo a 3 giorni;
  dopo il primo richiamo a 7. «Prepara messaggio» scrive WhatsApp, email o la traccia per una telefonata:
  **non manda mai nulla**, lo copi tu.
- **Contenuti**: post social, post LinkedIn, newsletter, articoli SEO, thread, script video, descrizione Google
  Business, anche per un cliente. «Ogni mese, in automatico» prepara le bozze del mese di un cliente (es. 4 post il
  giorno 1): restano da approvare.
- **Testi su richiesta**: ghostwriting, riscritture, traduzioni, testi per sito, proposte, script di vendita.
  Brief → bozza → correzioni (nuova versione) → consegnato. Le versioni vanno anche nella cartella del progetto.
- **SEO locale**: Jarvis controlla online scheda Google, directory, social e sito, confronta nome-indirizzo-telefono
  e propone i 3 interventi più utili. Rapporto salvato in `dati/seo/`.
- **Preventivi**: scegli cliente e voci del listino; si apre una pagina pronta da stampare o salvare in PDF.
  Puoi aggiungere il link di pagamento (Stripe, PayPal…). Accettato → il cliente diventa Cliente e partono i
  canoni mensili; Pagato → l'incasso va in Cassa.
- **Cassa**: incassi degli ultimi mesi, canoni da incassare, incassi a mano, **margine per cliente** (incassato
  contro costo reale dell'AI per quel cliente; in euro se imposti i prezzi nella scheda Uso).
- **Listino**: i prezzi dei siti e della gestione mensile sono quelli della skill Preventivo sito; **Contenuti, Testi,
  SEO locale e Scheda prodotto sono «da decidere»**. Un preventivo con prezzi da decidere resta in bozza.
- **Memoria**: note permanenti. Le «istruzioni» valgono sempre, le altre Jarvis le richiama quando servono.
  Funziona anche a voce: «Jarvis, ricordati che…».

## Altre novità
- **Potenza** (Impostazioni): da 1 a 100. Bassa = rapida ed economica; alta = più ricerche e verifica incrociata
  delle fonti. Il modello resta sempre lo stesso.
- **Blueprint → Scheda prodotto**: dalla foto di un prodotto prepara titolo, punti chiave, descrizione, specifiche
  (stime) e parole chiave per vendere online.
- **Pubblica online** (Siti web e scheda cliente): pubblica la demo come bozza (noindex) per avere un link.
  Con `NETLIFY_TOKEN` nel file `.env` lo fa Jarvis; senza, prepara uno zip da trascinare su https://app.netlify.com/drop.
- **Briefing**: nuova sezione «Lavoro» (chi richiamare, incassi, canoni, bozze).
- **Sala controllo**: 5 squadre nuove (Commerciale, Contenuti, Testi su richiesta, SEO locale, Amministrazione).

## Dove stanno i dati
Tutto in `~/jarvis/dati/` (clienti, contenuti, lavori, listino, preventivi, abbonamenti, incassi, memoria, seo):
resta solo sul Mac e non va su GitHub.

## Prova
1. Chiudi Jarvis (`Ctrl + C`) e riavvialo con `avvia_jarvis.command`.
2. Nel Terminale: «Squadre: 14 pronte» e «Jarvis 3.5 è pronto».
3. Apri **Produttività → Listino** e decidi i prezzi che mancano (puoi farlo anche più avanti).
4. Apri **Clienti**: Salicornia Jesolo è già lì come «Demo pronta». Prova «Prepara messaggio».
5. Dillo a voce: «Jarvis, ricordati che firmo sempre come Jonatan, web designer».
