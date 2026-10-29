"""Pipeline degli aggiornamenti, passo 1 (2026-10-29): dossier delle ultime 2 settimane per le idee di Claude.
Errori del bot (Notion BotErrors), modifiche al codice (git log) e rilasci (tag). Scrive dossier/dossier.md.
Repo PUBBLICO: il dossier resta nel runner, mai stampato né caricato tra gli artefatti (dentro ci sono messaggi di Daniele).
Variabili: NOTION_TOKEN.
"""
import json
import os
import subprocess
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

DB_ERRORS = "38b9d2a5-23ac-81f5-935c-c9b665d4330f"
dal = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")


def notion_errori():
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{DB_ERRORS}/query",
        data=json.dumps({"filter": {"property": "timestamp", "date": {"on_or_after": dal}}, "page_size": 100}).encode(),
        headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}", "Notion-Version": "2022-06-28", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        righe = json.load(r)["results"]
    testo = lambda p, k: "".join(t["plain_text"] for t in p["properties"][k].get("title" if k == "error" else "rich_text", []))
    return [{"errore": testo(p, "error"), "input": testo(p, "input")[:200], "quando": p["properties"]["timestamp"]["date"]["start"][:16],
             "risolto": p["properties"]["resolved"]["checkbox"]} for p in righe]


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()


try:
    errori = notion_errori()
except Exception as e:
    errori, nota = [], f"(lettura Notion fallita: {e})"
else:
    nota = ""
tipi = Counter(e["errore"][:80] for e in errori)
righe = [f"# Dossier AssistenteAI dal {dal}", "",
         f"## Errori del bot: {len(errori)} in 2 settimane {nota}",
         *[f"- {n}× {t}" for t, n in tipi.most_common(15)], "",
         "### Dettaglio (ultimi 30, con il messaggio che li ha causati)",
         *[f"- {e['quando']} {'✅' if e['risolto'] else '❌'} {e['errore'][:120]} ← «{e['input']}»" for e in errori[:30]], "",
         "## Modifiche al codice nelle 2 settimane", git("log", f"--since={dal}", "--format=- %ad %s", "--date=short") or "(nessuna)", "",
         "## Ultimi rilasci della pipeline", git("tag", "-l", "v*", "--sort=-v:refname", "-n1") or "(nessuno ancora)"]
os.makedirs("dossier", exist_ok=True)
open("dossier/dossier.md", "w", encoding="utf-8").write("\n".join(righe) + "\n")
print(f"dossier: {len(errori)} errori, {len(tipi)} tipi")
