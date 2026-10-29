"""Pipeline degli aggiornamenti, passo 5 (2026-10-29): la versione del rilascio dall'ultimo tag vX.Y.Z e dal tipo
scritto in prove/idea_<N>.json ("correzione" = terzo numero +1, "funzione" = secondo +1). Senza tag si parte da 1.0.0.
Uso: python .github/pipeline/versione.py <N>   → scrive in GITHUB_OUTPUT versione e cosa (testo per Daniele).
"""
import json
import os
import subprocess
import sys

voce = json.load(open(f"prove/idea_{sys.argv[1]}.json", encoding="utf-8"))
tag = subprocess.run(["git", "tag", "-l", "v*", "--sort=-v:refname"], capture_output=True, text=True).stdout.split()
a, b, c = map(int, (tag[0][1:] if tag else "1.0.0").split("."))
versione = f"{a}.{b}.{c + 1}" if voce["tipo"] == "correzione" else f"{a}.{b + 1}.0"
cosa = " ".join(voce["cosa"]) if isinstance(voce["cosa"], list) else voce["cosa"]
with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
    f.write(f"versione={versione}\ncosa={cosa.replace(chr(10), ' ')}\n")
print(versione, cosa)
