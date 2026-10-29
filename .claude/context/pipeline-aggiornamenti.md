# Pipeline degli aggiornamenti (2026-10-29, copiata da canva-bot-risultati e adattata)

Tutto su GitHub Actions + Claude Code con il token dell'abbonamento di Daniele (CLAUDE_CODE_OAUTH_TOKEN).
Repo PUBBLICO: niente artefatti, la stampa delle prove resta nel runner, le Issue senza dati personali.

## Giro
1. Idee (`.github/workflows/idee.yml`, domenica 18 UTC settimane pari, o a mano): `.github/pipeline/dossier.py`
   (errori Notion BotErrors, git log, tag) → Claude (`.github/prompts/idee.md`) max 5 idee → Issue `idea` +
   messaggio a Daniele con bottoni ✅ (`.github/pipeline/pubblica_idee.py`).
2. Scelta: ✅ → il bot (agents/pipeline_github.py, callback `gh:ai:scelta:N`) mette l'etichetta `scelta` con
   GH_PIPELINE_TOKEN. Lo stesso bot gestisce anche i bottoni di lineaverde-ops (`gh:ops:...`).
3. Lavoro (`lavoro.yml`, `.github/prompts/lavoro.md`): ramo `idea-N`, codice, prova `prove/prova_idea_N.py`,
   voce `prove/idea_N.json`, PR. Grande → solo piano. `con Daniele` → si ferma. Max 3 PR idea-* aperte.
4. Prova (stesso job, `.github/pipeline/anteprima.py`): deploy di anteprima, la prova manda update finti dal chat di
   Daniele al webhook dell'anteprima e legge `risposte` nel JSON del webhook. Dati veri (Notion, Calendar): solo letture o
   elementi "PROVA pipeline" cancellati. Fino a 2 correzioni. Messaggio "provato, x su y ✅. Rilascio?" con 🚀.
5. Rilascio (`rilascio.yml`): etichetta `rilascia` (🚀, solo il proprietario) → squash in main, versione da tag +
   tipo (`.github/pipeline/versione.py`), `vercel deploy --prod`, controllo, tag vX.Y.Z, push, avviso.

## Secrets GitHub
CLAUDE_CODE_OAUTH_TOKEN, VERCEL_TOKEN, VERCEL_AUTOMATION_BYPASS_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
WEBHOOK_SECRET, NOTION_TOKEN. Vercel Production: GH_PIPELINE_TOKEN. Vercel Preview: tutte tranne ENABLE_BANKING*,
WP_APP_*, TRACK17 (la banca e il sito non si toccano dall'anteprima).
