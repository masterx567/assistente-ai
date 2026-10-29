"""Pipeline degli aggiornamenti, passo 1 (2026-10-29): dalle idee di Claude (dossier/idee.json) alle Issue su GitHub
con l'etichetta "idea", poi un messaggio a Daniele su Telegram con un bottone ✅ per idea.
Variabili: GH_TOKEN, GITHUB_REPOSITORY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PROGETTO (ai/ops), NOME.
Uso: python .github/pipeline/pubblica_idee.py dossier/idee.json [--prova]  (--prova: solo stampa)
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

ETICHETTE = [
    {"name": "idea", "color": "1d8a3b", "description": "Proposta di Claude, da scegliere"},
    {"name": "scelta", "color": "e9c85a", "description": "Scelta da Daniele: Claude la sviluppa"},
    {"name": "rilascia", "color": "0e8a16", "description": "Sulla Pull Request provata: ok di Daniele al rilascio"},
    {"name": "con Daniele", "color": "b3261e", "description": "Tocca credenziali, Vercel o dati veri: si fa insieme"},
    {"name": "lavoro: piccolo", "color": "cfe0cf", "description": ""},
    {"name": "lavoro: medio", "color": "9db5a5", "description": ""},
    {"name": "lavoro: grande", "color": "4d6656", "description": "Solo piano, niente codice in automatico"},
]
LAVORO = {"piccolo": "🟢", "medio": "🟡", "grande": "🔴"}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def chiama(url, body=None, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 422:  # etichetta che c'è già
            return {}
        raise RuntimeError(f"{url}: {e.code} {e.read().decode()[:300]}")


def gh(path, body):
    return chiama(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}", body,
                  {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"})


def main():
    prova = "--prova" in sys.argv
    idee = json.load(open(sys.argv[1], encoding="utf-8"))[:5]
    if not idee:
        raise SystemExit("nessuna idea in idee.json")
    oggi = date.today()
    giro = f"{oggi.day} {MESI[oggi.month - 1]} {oggi.year}"
    create = []
    if not prova:
        for e in ETICHETTE:
            gh("/labels", e)
    for idea in idee:
        corpo = "\n\n".join([f"**Perché**\n{idea['perche']}", f"**Cosa cambia**\n{idea['cosa']}", f"**Come**\n{idea['come']}",
                             f"_Giro di idee del {giro}. Lavoro {idea['lavoro']}{', da fare con Daniele' if idea.get('conDaniele') else ''}._"])
        labels = ["idea", f"lavoro: {idea['lavoro']}"] + (["con Daniele"] if idea.get("conDaniele") else [])
        if prova:
            print(f"\n# {idea['titolo']} {labels}\n{corpo}")
            continue
        i = gh("/issues", {"title": idea["titolo"], "body": corpo, "labels": labels})
        create.append((idea, i["number"], i["html_url"]))
    if prova:
        return
    testo = "\n".join([f"💡 {os.environ['NOME']}: idee per il prossimo aggiornamento ({giro})", ""]
                      + [f"{LAVORO[idea['lavoro']]} {idea['titolo']}{' 🤝' if idea.get('conDaniele') else ''}\n{idea['perche']}\n#{n} {url}" for idea, n, url in create]
                      + ["", "🟢 piccolo · 🟡 medio · 🔴 grande (solo piano) · 🤝 da fare insieme", "Per sceglierne una (massimo 3): tocca ✅ qui sotto."])
    # ✅ #N mette l'etichetta "scelta" tramite il bot AssistenteAI (agents/pipeline_github.py). Grande e 🤝: niente bottone
    bottoni = [{"text": f"✅ #{n}", "callback_data": f"gh:{os.environ['PROGETTO']}:scelta:{n}"}
               for idea, n, _ in create if idea["lavoro"] != "grande" and not idea.get("conDaniele")]
    msg = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": testo[:4000], "link_preview_options": {"is_disabled": True}}
    if bottoni:
        msg["reply_markup"] = {"inline_keyboard": [bottoni]}
    chiama(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage", msg)
    print(f"{len(create)} Issue create, messaggio mandato a Daniele")


main()
