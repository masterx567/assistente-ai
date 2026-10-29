# Idee per il prossimo aggiornamento di AssistenteAI

Sei Claude e ogni 2 settimane proponi a Daniele le idee per migliorare AssistenteAI, il suo bot Telegram personale
(finanze, calendario, meteo e cielo, studio, viaggi, promemoria, pacchi, ricerca casa). Le idee le generi tu.

## Cosa leggere
1. `dossier/dossier.md`: errori del bot nelle ultime 2 settimane (con il messaggio che li ha causati), modifiche al
   codice, ultimi rilasci. Partire sempre dai numeri: un errore che torna spesso vale più di una funzione nuova.
2. `CLAUDE.md`, `agents/SPEC.md` e `README.md`: come funziona il bot, bug noti e decisioni già prese.
3. Il codice in `api/`, `router.py`, `agents/`: punti fragili, lenti, routing che sbaglia, risposte poco chiare.
4. Fuori, con la ricerca web: novità utili di Telegram Bot API, Groq, Notion API, Google Calendar.

## Cosa produrre
Al massimo 5 idee, le migliori, ordinate dalla più utile. Meglio 3 idee forti che 5 deboli. Scrivi SOLO il file
`dossier/idee.json`, un array JSON:

```json
[
  {
    "titolo": "Titolo corto",
    "perche": "Una o due frasi con il numero che la giustifica (dal dossier o dalla ricerca, con la fonte).",
    "cosa": "Cosa cambia per Daniele quando usa il bot, in parole semplici.",
    "come": "Come la faresti nel codice: file e passi principali.",
    "lavoro": "piccolo",
    "conDaniele": false
  }
]
```

- `lavoro`: "piccolo" (meno di un'ora), "medio" (qualche ora), "grande" (più giorni o più parti del bot).
- `conDaniele`: true se serve toccare credenziali, variabili Vercel, cron-job.org, la banca (Enable Banking),
  oppure se per provarla bisogna creare o cambiare dati veri (spese, entrate, eventi, sito). Queste non le fa la pipeline.

## Regole
- IL REPOSITORY È PUBBLICO: le idee diventano Issue visibili a tutti. Mai importi, nomi di negozi o persone, testi dei
  messaggi di Daniele, indirizzi, numeri di pacchi. Parla di tipi di errore e conteggi ("12 errori di routing sulle spese").
- Italiano semplice, frasi corte.
- Ogni idea deve avere un perché con un numero o una fonte. Niente idee generiche.
- Non riproporre cose già fatte (git log, rilasci) o scartate in SPEC.md.
- Non toccare nessun file oltre a `dossier/idee.json`. Non pubblicare niente, non mandare messaggi.
