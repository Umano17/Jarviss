# Jarvis 3.6 – Approvazioni su Telegram e Manutentore 24/7

## Approvazioni SÌ / NO
Le azioni critiche non partono più da sole e non serve essere davanti al Mac:
Jarvis prepara l'azione e ti manda su Telegram un messaggio con due pulsanti, **✅ SÌ** e **❌ NO**.
- SÌ → la esegue e nello stesso messaggio compare l'esito.
- NO → annullata. Senza risposta per 12 ore → annullata da sola.
- Puoi anche scrivere «sì» o «no» (con più richieste aperte: «sì 3», «no 4»).
- Le stesse richieste compaiono sulla schermata nel riquadro «Da approvare», con i pulsanti SÌ / NO.

Cosa chiede il SÌ: inviare un'email, creare o cancellare un evento in agenda, togliere un volo monitorato,
riattivare il trader, pubblicare online una demo. **Fermare il trader resta immediato** (è una sicurezza).
Solo tu puoi approvare: il bot accetta pulsanti e risposte solo dal tuo account Telegram, e Jarvis non può
approvare da solo.

## Manutentore 24/7
Nuova squadra **Manutenzione** nella Sala controllo: Ispettore, Netturbino, Architetto.
- **Ogni ora** (gratis): controlla che tutti i moduli funzionino e siano collegati tra loro, che i dati siano
  leggibili, che le skill e il file .env siano a posto, che il trader aggiorni i suoi file in orario.
- **Pulizia sicura**: archivia registri troppo lunghi, zip vecchi e cache inutili in `dati/archivio/`.
  Niente viene cancellato davvero.
- Ti scrive su Telegram **solo** quando compare un problema nuovo.
- **Ogni lunedì** l'Architetto propone i 3 miglioramenti più utili al codice (pochi centesimi).
  Per spegnerlo: `MANUTENZIONE_ARCHITETTO=no` nel file `.env`.
- Il Manutentore **non modifica mai il codice da solo**: propone, e le modifiche le decidi tu.
- Lavora finché il Mac è acceso e Jarvis aperto: con il Mac spento o in stop si ferma anche lui.

## Incongruenze sistemate
- La skill «trader-notizie» ora usa il file che il trader legge davvero (`jarvis_notizie.txt`).
- La soglia di affidabilità dei risultati è la stessa ovunque (50+ operazioni e 4 settimane).
- La documentazione indica il trader attivo giusto (JarvisScalper v3.2 su demo AvaTrade).

## Prova
1. Chiudi Jarvis (`Ctrl + C`) e riavvialo con `avvia_jarvis.command`.
2. Nel Terminale: «Squadre: 15 pronte» e «Jarvis 3.6 è pronto».
3. Dì a Jarvis: «crea un evento domani alle 10, prova approvazione». Su Telegram arriva la richiesta: premi NO.
4. Controllo a mano del Manutentore, dal Terminale dentro `~/jarvis`: `python manutentore.py`.
