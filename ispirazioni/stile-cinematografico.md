# Stile CINEMATOGRAFICO

Atmosfera, luce, scene. Riferimenti: REF-01 Satellite (Edolus), REF-10 Allta, demo Alambicco 47.

## Aspetto
- Fondo profondo (notte, ombra calda) con una luce calda o un colore che "illumina" la scena: ambra, rame, rubino, blu notte, scelti dal locale.
- Caratteri: un display elegante o scritto a mano per il nome, un monospaziato per le "didascalie da inquadratura" (CAM_01 / SALA, REC_01), un testo leggibile per il resto.
- Poco testo, frasi brevi, molto spazio.

## Struttura
- Ogni sezione è una SCENA: cambia luce, colore di fondo o immagine passando da una all'altra (il menu è un viaggio tra luoghi).
- Una scena principale fissa (sticky) mentre il testo scorre sopra.
- Cornici da inquadratura agli angoli, piccole croci "+", codici di scena.
- Informazioni pratiche sempre raggiungibili: barra fissa in basso su telefono (Prenota / Chiama / Orari) e sezione finale chiara.

## Componenti dalla libreria (solo dove il livello li permette)
- Scena guidata dallo scorrimento disegnata in SVG/CSS/canvas legata al mestiere (es. bicchiere che si riempie a strati per un cocktail bar, forno che si accende per una pizzeria, forbici che si aprono per un barbiere).
- Titoli che si decodificano all'ingresso.
- Mazzo di foto impilate allo scorrimento.
- Nastro scorrevole in alto SOLO con un'informazione vera (premio, evento).
- Fumo / particelle leggere in canvas, poche e lente.

## Da evitare
- Animazioni pesanti sui telefoni economici: niente modelli 3D, canvas con al massimo ~60 particelle, pausa quando la scheda non è visibile.
- Tutte le animazioni spente con prefers-reduced-motion.
