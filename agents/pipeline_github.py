"""Pipeline degli aggiornamenti (2026-10-29): bottoni nei messaggi a Daniele che mettono un'etichetta su GitHub.

callback_data "gh:<progetto>:<etichetta>:<numero>":
  gh:ai:scelta:12     → etichetta "scelta" sulla Issue 12 di assistente-ai: parte il workflow Lavoro (codice, PR, prova)
  gh:ops:rilascia:7   → etichetta "rilascia" sulla PR 7 di lineaverde-ops: parte il workflow Rilascio
Lo stesso bot avvisa per assistente-ai e lineaverde-ops (stesso TELEGRAM_TOKEN). GH_PIPELINE_TOKEN è un token GitHub
fine-grained di Daniele (Issues + Pull requests in scrittura su questi repo): un'etichetta messa col suo token fa partire
i workflow e passa il controllo "solo il proprietario" del rilascio.
"""
import os
import httpx

REPO = {"ai": "masterx567/assistente-ai", "ops": "masterx567/lineaverde-ops"}
FATTO = {"scelta": "✅ Scelta: Claude la sviluppa e la prova", "rilascia": "🚀 Rilascio avviato: tra pochi minuti arriva l'avviso"}


def handle_pipeline_button(data: str, markup: dict | None) -> dict:
    """Mette l'etichetta e ritorna {"text": conferma, "markup": bottoni rimasti}."""
    parti = data.split(":")
    if len(parti) != 4 or parti[1] not in REPO or parti[2] not in FATTO or not parti[3].isdigit():
        return {"text": f"Bottone non valido: {data}", "markup": markup}
    _, progetto, etichetta, numero = parti
    r = httpx.post(
        f"https://api.github.com/repos/{REPO[progetto]}/issues/{numero}/labels",
        headers={"Authorization": f"Bearer {os.getenv('GH_PIPELINE_TOKEN')}", "Accept": "application/vnd.github+json"},
        json={"labels": [etichetta]},
        timeout=8,
    )
    if r.status_code >= 300:
        return {"text": f"GitHub non ha accettato ({r.status_code}). Metti l'etichetta «{etichetta}» a mano su {REPO[progetto]}#{numero}.", "markup": markup}
    # Tolto il bottone toccato, restano gli altri (le idee sono più di una nello stesso messaggio)
    righe = [[b for b in riga if b.get("callback_data") != data] for riga in (markup or {}).get("inline_keyboard", [])]
    righe = [riga for riga in righe if riga]
    return {"text": f"{FATTO[etichetta]} ({REPO[progetto].split('/')[1]} #{numero})", "markup": {"inline_keyboard": righe}}
