---
name: riepilogo-giornata
description: Riepilogo a voce della giornata: impegni in agenda, meteo, richiami dei clienti e bozze da approvare. Usala la mattina o quando l'utente chiede com'è la giornata.
metadata:
  categoria: Produttività
  conferma: no
---

# Riepilogo della giornata

Obiettivo: in meno di 60 secondi di parlato, dire all'utente cosa lo aspetta oggi.

## Passi
1. Leggi gli impegni di oggi dall'agenda collegata (funzione agenda di Jarvis). Se non è disponibile, dillo in una frase e salta il punto.
2. Leggi meteo e temperatura della posizione attuale.
3. Controlla il lavoro (produttivita_stato): clienti da richiamare oggi e contenuti in bozza da approvare.
4. Chiudi con il primo impegno della giornata e quanto tempo manca.

## Stile
- Parla, non elencare: frasi brevi, niente simboli, niente link letti ad alta voce.
- Orari detti come "alle nove e mezza", non "09:30".
- Nessuna scusa, nessun preambolo. Professionale e diretto.
