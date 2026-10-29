"""Pipeline degli aggiornamenti, passo 4 (2026-10-29): anteprima Vercel del ramo e prova reale.
  1. deploy di anteprima (mai --prod): le funzioni girano su un indirizzo a parte, la produzione non cambia
  2. lancia prove/prova_idea_<N>.py con BASE_URL = anteprima; la prova stampa "RISULTATO: x/y" ed esce 1 se qualcosa fallisce
Variabili: VERCEL_TOKEN, VERCEL_ORG_ID, VERCEL_PROJECT_ID, VERCEL_AUTOMATION_BYPASS_SECRET e quelle della prova.
Uso: python .github/pipeline/anteprima.py <numero Issue>
Scrive in GITHUB_OUTPUT: url, esito (ok/ko), risultato ("3/3"). La stampa della prova va SOLO in dossier/prova-<N>.log
(letto da Claude se deve correggere): nel log pubblico del workflow esce solo il risultato.
"""
import os
import re
import subprocess
import sys

n = sys.argv[1]
prova = f"prove/prova_idea_{n}.py"


def out(k, v):
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"{k}={v.replace(chr(10), ' ')}\n")


def fine(esito, risultato, url=""):
    out("url", url)
    out("esito", esito)
    out("risultato", risultato)
    print(f"esito {esito}, {risultato}")
    sys.exit(0 if esito == "ok" else 1)


d = subprocess.run(["npx", "-y", "vercel", "deploy", "--yes", "--token", os.environ["VERCEL_TOKEN"]], capture_output=True, text=True)
m = re.search(r"https://[a-z0-9-]+\.vercel\.app", d.stdout)
if d.returncode or not m:
    print(f"deploy di anteprima fallito:\n{d.stderr[-2000:]}")
    fine("ko", "anteprima non creata")
url = m.group(0)
print(f"anteprima {url}")
if not os.path.exists(prova):
    fine("ko", f"manca {prova}", url)

os.makedirs("dossier", exist_ok=True)
try:
    p = subprocess.run([sys.executable, prova], capture_output=True, text=True, timeout=15 * 60, env={**os.environ, "BASE_URL": url})
    stampa, ok = p.stdout + "\n" + p.stderr, p.returncode == 0
except subprocess.TimeoutExpired as e:
    stampa, ok = f"{e.stdout or ''}\nprova interrotta dopo 15 minuti", False
open(f"dossier/prova-{n}.log", "w", encoding="utf-8").write(stampa)
r = re.search(r"RISULTATO:\s*(\d+\s*/\s*\d+)", stampa)
fine("ok" if ok else "ko", re.sub(r"\s", "", r.group(1)) if r else ("?" if ok else "prova interrotta"), url)
