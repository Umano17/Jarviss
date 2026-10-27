# Jarvis 3.7 – Base sicura e più AI collegate

## Cosa cambia

| Novità | Dove | Come si usa |
|---|---|---|
| **AI di riserva** | `ai.py` | Se Claude non risponde, Jarvis passa da solo a Gemini, OpenAI, Ollama o OpenRouter e ti avvisa su Telegram. Guida: `LEGGIMI-AI.md` |
| **Tetto di spesa** | `ai.py`, scheda Uso | `TETTO_SPESA_MESE=40` nel `.env`: avviso al 75%, al 100% restano solo le AI gratuite |
| **Guardiano** | `avvio.py`, `avvia_jarvis.command` | Avvia Jarvis; dopo un aggiornamento controlla che riparta sano, altrimenti torna da solo alla versione precedente |
| **Aggiornamenti da Telegram** | `aggiornamenti.py` | `/aggiorna` mostra cosa cambia e chiede SÌ/NO; `/versione`; `/riavvia` |
| **Zona sacra + codice** | `zona_sacra.py`, `approvazioni.py` | Se un aggiornamento tocca un file sacro, dopo il SÌ arriva su Telegram un codice di 6 cifre (5 minuti, una volta, 3 tentativi) da riscrivere su Telegram o sulla schermata |
| **Fuso orario** | `orario.py`, Impostazioni | Scegli il fuso (o usa quello del dispositivo): ora di Jarvis, briefing, notizie, dispensa, agenda. Il trader resta sugli orari di mercato |
| **Instagram manuale** | `prompt/instagram_jarvy.md`, Telegram | `/post consiglio come rispondere alle recensioni` (o chiedilo a Jarvis): la bozza arriva su Telegram pronta da copiare; pubblichi a mano su @jarvy.studio e premi «Pubblicato» |
| **Sezione File** | scheda «File» | Vedi e scarichi demo, progetti, rapporti SEO e manutenzione (solo quelle cartelle: niente `.env` né dati personali) |

## Cosa devi fare tu

1. **Chiudi Jarvis** (`Ctrl + C` nel Terminale) e **riaprilo con doppio clic su `avvia_jarvis.command`**: ora parte il guardiano. Nel Terminale compare `Jarvis 3.7 è pronto`.
2. Su Telegram scrivi **`/versione`**: deve rispondere con ramo `jarvis-3.7` e «Guardiano: attivo».
3. **Collega le AI di riserva** seguendo `LEGGIMI-AI.md` (Gemini gratis e Ollama sono le più semplici), poi `python ai.py` per provarle.
4. In **Impostazioni → Fuso orario** premi «Usa quello di questo dispositivo».

## Come funziona un aggiornamento

1. Lo sviluppo carica le modifiche su GitHub (ramo `jarvis-3.7`, repository privato).
2. Tu scrivi `/aggiorna` su Telegram: Jarvis elenca le modifiche e chiede SÌ/NO (con il codice se tocca la zona sacra).
3. Dopo il SÌ: avanzamento senza unioni automatiche, controllo che il codice si compili, riavvio.
4. Se entro 90 secondi Jarvis non risponde, il guardiano torna alla versione di prima e ti avvisa.

I dati (`dati/`, `.env`, configurazioni, demo, progetti) non sono su GitHub e un aggiornamento non li tocca mai.

## Prova fatta

- Riserva: con il credito di Claude finito la stessa domanda (anche con strumenti) viene servita dalla riserva; quando Claude torna, si torna a Claude.
- Codice: giusto → esegue; 3 sbagliati → annullata; scaduto → annullata; la richiesta normale resta con il solo SÌ.
- Guardiano: un aggiornamento buono riparte e conferma; un aggiornamento che si blocca all'avvio torna da solo alla versione precedente.
- File: si scaricano solo i file delle cartelle ammesse (`.env`, `dati/accesso_segreto.txt`, percorsi con `..` → rifiutati).
