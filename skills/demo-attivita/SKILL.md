---
name: demo-attivita
description: Crea una demo di sito web per un'attività locale senza sito partendo da nome e località, nello stile e nel livello scelti, con consiglio di stile, scheda dati e messaggio per il titolare. Usala quando l'utente vuole preparare una demo o una proposta di sito per un locale.
metadata:
  categoria: Lavoro siti
  titolo: Demo attività
  conferma: no
---

# Demo sito per attività locale

## Passi
1. **Identifica l'attività**: servono nome e località. Se arriva un link Google Maps lungo, prendi il nome dopo `/place/`. Se è un link breve o manca la città, chiedili con una sola domanda.
2. **Scegli stile e livello** con una sola domanda, se l'utente non li ha già detti:
   - stile: Classico, Futuristico, Cinematografico, oppure "decidi tu" (= `auto`, lo sceglie Jarvis dopo la ricerca);
   - livello: ★★★ (bello e scorrevole, menu curato non animato), ★★★★ (prenotazione WhatsApp e menu scorrevole), ★★★★★★ (ultrapregiato e interattivo).
   Se risponde "decidi tu" a tutto: stile `auto`, livello `3`.
3. **Avvia la demo** con lo strumento `sito_demo_crea` (nome, città, `stile`, `livello`, eventuale nota). Fa da solo: ricerca dei dati pubblici, controllo se ha già un sito, consiglio di stile, pagina demo, scheda dati e messaggio per il titolare.
4. Di' a voce che è partita e che tra un paio di minuti la trova nel riquadro **Siti web**. Non aspettare in silenzio.
5. Se l'utente chiede a che punto è, usa `siti_demo_elenco`. Lì trovi anche lo **stile consigliato** da Jarvis e il motivo.
6. Se lo stile consigliato è diverso da quello scelto, riferiscilo in una frase con il motivo e chiedi se rifarla nello stile consigliato: in quel caso `sito_demo_crea` con lo stesso nome e città, il nuovo `stile`, lo stesso `livello` e `riusa: true` (non ripete la ricerca). La versione precedente resta salvata.
7. Se il risultato è "ha già un sito curato", dillo e chiedi se vuole comunque una proposta di rifacimento (solo allora `forza: true`).
8. A demo pronta, ricorda le cose da verificare con il titolare (sono nella scheda) e chiudi la skill con `skill_disattiva`.

## Regole
- Mai foto di clienti o di Google: solo foto dei canali dell'attività, con permesso scritto.
- Mai dati, prezzi o recensioni inventati.
- La demo non si pubblica online finché il titolare non dice sì.
- I file stanno in `demo/<nome-attivita>/` dentro la cartella di Jarvis: `index.html` è l'ultima versione, `index-<stile>-<livello>.html` le versioni per stile e livello.
- Le regole di ogni stile e livello sono nella cartella `ispirazioni/` (libreria dei riferimenti e guide degli stili).
