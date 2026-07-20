"""Sostituzione allegati (PDF/foto) sul sito lineaverdeonline.com via WP REST API.

Flusso: Daniele manda un allegato su Telegram con una descrizione ("sostituisci il
regolamento safeguarding") -> il bot cerca la pagina giusta, trova il link/immagine
esistente da sostituire, chiede conferma, poi carica il nuovo file e aggiorna il link.

Regola fissa: solo sostituzioni di roba GIA' esistente. Se non trova niente da
sostituire, si ferma e lo dice — non aggiunge mai contenuto nuovo in autonomia.
"""
import os
import re
import json
import httpx

WP_URL = "https://www.lineaverdeonline.com"
WP_APP_USER = os.getenv("WP_APP_USER")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_AUTH = httpx.BasicAuth(WP_APP_USER or "", WP_APP_PASSWORD or "")

_MEDIA_URL_RE = re.compile(
    r'(?:href|src)="([^"]+\.(?:pdf|jpe?g|png|webp))"', re.IGNORECASE
)


async def _download_telegram_file(file_id: str) -> bytes | None:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
                              params={"file_id": file_id})
        file_path = r.json().get("result", {}).get("file_path")
        if not file_path:
            return None
        f = await client.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
        if f.status_code != 200:
            return None
        return f.content


async def _search_pages(query: str) -> list[dict]:
    """Cerca tra pagine e articoli WP che matchano la query. Ritorna [{id, title, link, type}]."""
    results = []
    async with httpx.AsyncClient(timeout=10, auth=_AUTH) as client:
        for post_type in ("pages", "posts"):
            r = await client.get(f"{WP_URL}/wp-json/wp/v2/{post_type}",
                                  params={"search": query, "per_page": 8})
            if r.status_code != 200:
                continue
            for item in r.json():
                results.append({
                    "id": item["id"],
                    "title": item["title"]["rendered"],
                    "link": item["link"],
                    "type": post_type,
                })
    return results


async def _get_raw_content(page_id: int, post_type: str) -> str:
    async with httpx.AsyncClient(timeout=10, auth=_AUTH) as client:
        r = await client.get(f"{WP_URL}/wp-json/wp/v2/{post_type}/{page_id}",
                              params={"context": "edit"})
        r.raise_for_status()
        return r.json()["content"]["raw"]


async def _find_reference(content: str, description: str) -> str | None:
    """Trova, tra i link/immagini presenti nel contenuto, quello che meglio corrisponde
    alla descrizione. Ritorna l'URL da sostituire, o None se non c'è un match sicuro."""
    candidates = list(dict.fromkeys(_MEDIA_URL_RE.findall(content)))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    prompt = f"""Devi trovare quale di questi URL corrisponde alla descrizione data.
Descrizione: "{description}"
URL disponibili:
{chr(10).join(f"{i}. {u}" for i, u in enumerate(candidates))}

Rispondi SOLO con il numero dell'URL che corrisponde meglio, oppure "nessuno" se nessuno
corrisponde con sicurezza. Zero altro testo."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 10, "temperature": 0})
    raw = r.json()["choices"][0]["message"]["content"].strip().lower()
    m = re.search(r"\d+", raw)
    if not m or "nessuno" in raw:
        return None
    idx = int(m.group())
    return candidates[idx] if 0 <= idx < len(candidates) else None


async def _upload_media(file_bytes: bytes, filename: str, mime: str) -> dict:
    async with httpx.AsyncClient(timeout=30, auth=_AUTH) as client:
        r = await client.post(f"{WP_URL}/wp-json/wp/v2/media",
            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                     "Content-Type": mime},
            content=file_bytes)
        r.raise_for_status()
        data = r.json()
        return {"id": data["id"], "url": data["source_url"]}


async def _replace_url_in_content(page_id: int, post_type: str, old_url: str, new_url: str) -> str:
    content = await _get_raw_content(page_id, post_type)
    new_content = content.replace(old_url, new_url)
    async with httpx.AsyncClient(timeout=15, auth=_AUTH) as client:
        r = await client.post(f"{WP_URL}/wp-json/wp/v2/{post_type}/{page_id}",
            json={"content": new_content})
        r.raise_for_status()
        return r.json()["link"]


def _numbered_list(candidates: list[dict]) -> str:
    lines = [f"{i+1}. {c['title']} ({c['type']})" for i, c in enumerate(candidates)]
    return "\n".join(lines)


async def start_replace_flow(file_id: str, filename: str, mime: str, description: str,
                              save_pending, get_pending, clear_pending) -> dict:
    """Punto d'ingresso: allegato + descrizione ricevuti. Cerca la pagina, trova il
    riferimento da sostituire, chiede conferma. Ritorna {"text":..., "markup":...}."""
    candidates = await _search_pages(description)
    if not candidates:
        return {"text": f"Non trovo nessuna pagina che corrisponda a \"{description}\". "
                         f"Dimmi tu il nome esatto della pagina sul sito."}

    if len(candidates) > 1:
        await save_pending("site_media_choose_page", {
            "file_id": file_id, "filename": filename, "mime": mime,
            "description": description,
            "candidates": candidates,
        })
        return {"text": "Ho trovato più pagine possibili, quale intendi?\n\n"
                         + _numbered_list(candidates)
                         + "\n\nRispondi con il numero."}

    return await _resolve_candidate(candidates[0], file_id, filename, mime, description, save_pending)


async def _resolve_candidate(candidate: dict, file_id: str, filename: str, mime: str,
                              description: str, save_pending) -> dict:
    content = await _get_raw_content(candidate["id"], candidate["type"])
    old_url = await _find_reference(content, description)
    if not old_url:
        return {"text": f"Non trovo niente da sostituire in \"{candidate['title']}\" che "
                         f"corrisponda alla tua descrizione. Se è un contenuto nuovo, "
                         f"quello lo faccio a mano."}

    await save_pending("site_media_confirm", {
        "file_id": file_id, "filename": filename, "mime": mime,
        "page_id": candidate["id"], "post_type": candidate["type"],
        "page_title": candidate["title"], "old_url": old_url,
    })
    return {"text": f"Trovato in *{candidate['title']}*:\n`{old_url}`\n\n"
                     f"Lo sostituisco con *{filename}*. Confermi?"}


async def choose_page(payload: dict, choice_text: str, save_pending) -> dict:
    """Secondo step: Daniele ha risposto con un numero alla lista di pagine candidate."""
    m = re.search(r"\d+", choice_text)
    if not m:
        return {"text": "Rispondi con il numero della pagina."}
    idx = int(m.group()) - 1
    candidates = payload["candidates"]
    if not (0 <= idx < len(candidates)):
        return {"text": f"Numero non valido, scegli tra 1 e {len(candidates)}."}
    return await _resolve_candidate(candidates[idx], payload["file_id"], payload["filename"],
                                     payload["mime"], payload["description"], save_pending)


async def confirm_replace(payload: dict) -> str:
    """Ultimo step: Daniele ha confermato. Scarica il file da Telegram, lo carica su WP,
    sostituisce il vecchio URL nella pagina."""
    file_bytes = await _download_telegram_file(payload["file_id"])
    if not file_bytes:
        return "⚠️ Non sono riuscito a scaricare il file da Telegram, riprova."
    media = await _upload_media(file_bytes, payload["filename"], payload["mime"])
    link = await _replace_url_in_content(payload["page_id"], payload["post_type"],
                                          payload["old_url"], media["url"])
    return f"✅ Sostituito in *{payload['page_title']}* — {link}"
