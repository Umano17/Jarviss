# Collegare le AI di riserva a Jarvis (3.7)

Claude resta il cervello. Se Claude non risponde (credito finito, chiave sbagliata, servizio sovraccarico) Jarvis passa da solo alla prima riserva che trova nel file `.env`, ti avvisa su Telegram e torna a Claude appena risponde di nuovo.

In riserva funzionano la conversazione, gli strumenti di Jarvis (agenda, clienti, contenuti, trader…) e le foto. **Non funziona la ricerca web** (è una funzione di Claude): in riserva Jarvis lo dice e non inventa fonti.

## 1. Apri il file .env

Nel Terminale:

```bash
open -e ~/jarvis/.env
```

Aggiungi in fondo le righe delle AI che vuoi collegare (anche una sola basta). **Le chiavi non vanno mai mandate in chat a nessuno.**

## 2. Google Gemini (consigliata: ha un piano gratuito)

1. Vai su https://aistudio.google.com e accedi con il tuo account Google.
2. Clicca **Get API key** → **Create API key**.
3. Copia la chiave e nel `.env` scrivi:

```
GEMINI_API_KEY=incolla-qui-la-chiave
GEMINI_MODELLO=gemini-3.6-flash
```

## 3. OpenAI (a consumo)

1. Vai su https://platform.openai.com → **API keys** → **Create new secret key**.
2. In **Billing** aggiungi un piccolo credito (es. 5 $) e, se vuoi, un limite mensile.
3. Nel `.env`:

```
OPENAI_API_KEY=incolla-qui-la-chiave
OPENAI_MODELLO=gpt-6-luna
```

## 4. AI locale con Ollama (gratis, funziona anche senza credito)

1. Scarica Ollama da https://ollama.com/download e aprilo (compare l'icona del lama in alto).
2. Nel Terminale scarica un modello leggero:

```bash
ollama pull llama3.2
```

3. Nel `.env`:

```
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODELLO=llama3.2
```

È più lenta e meno brava di Claude, ma è il paracadute: i dati non escono dal Mac.

## 5. OpenRouter (facoltativo: una chiave per tanti modelli)

1. https://openrouter.ai → **Keys** → **Create Key**, poi aggiungi credito.
2. Nel `.env`:

```
OPENROUTER_API_KEY=incolla-qui-la-chiave
OPENROUTER_MODELLO=openrouter/auto
```

## 6. Ordine delle riserve e tetto di spesa

```
AI_ORDINE=gemini,openai,ollama,openrouter
TETTO_SPESA_MESE=40
```

- `AI_ORDINE`: in che ordine provare le riserve (si salta chi non ha la chiave).
- `TETTO_SPESA_MESE`: euro al mese. Al 75% arriva un avviso; al 100% le AI a pagamento (Claude, OpenAI, OpenRouter) si fermano e restano solo Gemini gratuito e Ollama, fino al mese dopo.

## 7. Prova

Salva il `.env`, poi nel Terminale:

```bash
cd ~/jarvis && source venv/bin/activate && python ai.py
```

Per ogni AI vedi «risponde» oppure «NON risponde» con il motivo. Se un modello «non esiste», controlla il nome esatto sul sito del fornitore (i nomi cambiano spesso) e correggi la riga `..._MODELLO`.

Poi riavvia Jarvis (`Ctrl + C` nel Terminale e doppio clic su `avvia_jarvis.command`). Nella scheda **Uso** trovi il riquadro **AI collegate**: cervello, riserve, quale AI sta rispondendo adesso e la spesa del mese.

## Se lo sviluppo con Claude si ferma

Questo collega le riserve a **Jarvis**, non alla sessione di sviluppo. Se finisce il credito della chat con Claude puoi continuare con un altro assistente di programmazione nella cartella `~/jarvis`, chiedendogli di:

1. leggere `CLAUDE.md` e `LEGGIMI-AGGIORNAMENTO-3.7.md`;
2. lavorare su un ramo nuovo (`git checkout -b prova-<nome>`), mai direttamente su `jarvis-3.7`;
3. non toccare i file della zona sacra (elenco in `zona_sacra.py`) e non indebolire sicurezza e approvazioni.

Quando torni con Claude, le sue modifiche si controllano prima di unirle.
