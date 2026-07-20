# Architettura

Spec completa già in `agents/SPEC.md` (stack, file principali, DB IDs, env vars, cron) — non duplicare qui, tenerlo aggiornato lì.

## Attenzione naming
`agents/` in questo progetto è codice applicativo del bot (moduli budget/calendar/news/...), NON subagent Claude Code. Eventuali subagent Claude vanno in `.claude/agents/`, cartella distinta.
