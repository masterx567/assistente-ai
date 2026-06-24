"""
Esegui questo script UNA VOLTA in locale per ottenere il refresh token Google.
Poi aggiungi GOOGLE_REFRESH_TOKEN alle variabili d'ambiente di Vercel.
"""
import httpx
import json
import urllib.parse
import webbrowser
import sys

CLIENT_ID = input("Client ID: ").strip()
CLIENT_SECRET = input("Client Secret: ").strip()

SCOPE = "https://www.googleapis.com/auth/calendar"
REDIRECT = "urn:ietf:wg:oauth:2.0:oob"

auth_url = (
    "https://accounts.google.com/o/oauth2/auth"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT)}"
    f"&scope={urllib.parse.quote(SCOPE)}"
    "&response_type=code"
    "&access_type=offline"
    "&prompt=consent"
)

print("\nApro il browser per l'autorizzazione...")
webbrowser.open(auth_url)
print(f"\nSe non si apre, vai su:\n{auth_url}\n")

code = input("Incolla il codice di autorizzazione: ").strip()

r = httpx.post("https://oauth2.googleapis.com/token", data={
    "code": code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": REDIRECT,
    "grant_type": "authorization_code",
})

data = r.json()
if "refresh_token" not in data:
    print("ERRORE:", data)
    sys.exit(1)

print("\n=== COPIA QUESTE VARIABILI SU VERCEL ===")
print(f"GOOGLE_CLIENT_ID={CLIENT_ID}")
print(f"GOOGLE_CLIENT_SECRET={CLIENT_SECRET}")
print(f"GOOGLE_REFRESH_TOKEN={data['refresh_token']}")
