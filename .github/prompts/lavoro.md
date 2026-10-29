# Sviluppare un'idea scelta da Daniele

Sei Claude e sviluppi una delle idee scelte da Daniele per AssistenteAI, il suo bot Telegram personale. L'idea è la
Issue indicata nel messaggio (titolo e testo in `dossier/issue.md`). Sei già su un ramo nuovo: il workflow fa commit,
Pull Request, anteprima e prova. Tu scrivi solo i file.

## Prima di toccare il codice
1. `CLAUDE.md` e `agents/SPEC.md`: come funziona il bot, ordine del routing (CRITICO), bug noti.
2. `dossier/issue.md`: cosa chiede l'idea.
3. Il codice coinvolto in `api/index.py`, `router.py`, `agents/`. Una prova già fatta in `prove/` se c'è.

## Cosa produrre
1. **Il codice** dell'idea, il più semplice possibile, nello stile dei file intorno.
2. **La prova**: `prove/prova_idea_<N>.py` (N = numero della Issue), solo libreria standard Python (urllib). Regole:
   - Manda al webhook dell'anteprima `POST {BASE_URL}/api/webhook` un update Telegram finto
     `{"update_id": 1, "message": {"message_id": 1, "chat": {"id": <TELEGRAM_CHAT_ID>}, "text": "..."}}` con gli header
     `X-Telegram-Bot-Api-Secret-Token: <WEBHOOK_SECRET>` e `x-vercel-protection-bypass: <VERCEL_AUTOMATION_BYPASS_SECRET>`.
   - La risposta JSON ha `"risposte"`: i testi che il bot ha mandato a Daniele. Controlla lì l'effetto di ogni caso.
     Il bot li manda davvero nella chat di Daniele: fai pochi casi (massimo 5) e chiari.
   - DATI VERI: l'anteprima usa gli stessi Notion, Google Calendar e Groq della produzione. Usa solo comandi che
     leggono. Se un caso deve creare qualcosa (promemoria, voce Notion), il titolo comincia con "PROVA pipeline" e la
     prova lo cancella alla fine (archiviando la pagina Notion con `NOTION_TOKEN`). Mai spese, entrate, eventi del
     calendario, banca, sito lineaverdeonline.com, conferme "sì" di operazioni vere.
   - Alla fine stampa `RISULTATO: x/y` (casi riusciti su casi totali) ed esce con codice 1 se x < y.
   - Le variabili arrivano dall'ambiente (`BASE_URL`, `WEBHOOK_SECRET`, `TELEGRAM_CHAT_ID`,
     `VERCEL_AUTOMATION_BYPASS_SECRET`, `NOTION_TOKEN`): niente lettura di `.env`.
3. **La documentazione**: aggiorna `agents/SPEC.md` (e `README.md` se cambia cosa sa fare il bot).
4. **La voce del rilascio** in `prove/idea_<N>.json`:
   ```json
   {
     "tipo": "funzione",
     "cosa": "Cosa cambia per Daniele, in una frase semplice.",
     "tecnico": "File e funzioni toccati.",
     "verifica": "La riempie il workflow con il risultato della prova: lascia questa frase.",
     "file": ["agents/...", "prove/prova_idea_N.py", "prove/idea_N.json"],
     "ritorno": "Come tornare indietro."
   }
   ```
   `tipo`: "correzione" o "funzione".
5. `python3 -m py_compile` sui file toccati deve passare.

## Se ti chiedono di correggere
Se nel messaggio c'è "correggi", la prova è fallita: leggi `dossier/prova-<N>.log`, trova la causa nel codice o nella
prova e correggila. Non indebolire la prova per farla passare.

## Limiti fissi
- Repository PUBBLICO: nei file mai dati personali (importi, nomi, ID Notion nuovi in chiaro vanno bene solo se già nel codice).
- Mai `vercel.json`, `.github/`, variabili d'ambiente nuove, credenziali, `agents/enable_banking.py`.
- Mai deploy, mai push: lo fa il workflow.
- Italiano semplice nei testi del bot e nei commenti.
- Se l'idea non si può fare senza violare questi limiti, non scrivere codice: scrivi solo `dossier/blocco.md` con il motivo.
