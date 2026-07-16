import httpx
import os
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_GYMGAME = "ba636571a56e404e927c2b0197506963"
DB_GYMCHECKINS = "fcc6c148fae142a9b142f9c95331d328"
ROME = ZoneInfo("Europe/Rome")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

WEEKLY_TARGET = 3
OLTRE_OBIETTIVO = 5
XP_CHECKIN = 10
XP_DUP = {"Comune": 5, "Rara": 15, "Epica": 30, "Leggendaria": 60, "Divinita": 120}
XP_WEEK_FAIL = 15
SHIELD_EVERY_LEVELS = 5
SHIELD_MAX = 3

LEAGUES = [
    (1, 5, "Bronzo"), (6, 10, "Argento"), (11, 15, "Oro"),
    (16, 20, "Platino"), (21, 25, "Diamante"), (26, None, "Leggenda"),
]

RARITY_WEIGHTS = [("Comune", 60), ("Rara", 25), ("Epica", 10), ("Leggendaria", 4), ("Divinita", 1)]

CREATURES = {
    "Comune": [("Chiocciolix", "🐌"), ("Ranocchip", "🐸"), ("Molliflop", "🦥"), ("Topazzin", "🐭"),
               ("Codablitz", "🐿️"), ("Criceridge", "🐹"), ("Pelosnap", "🐩"), ("Miciolin", "🐈"),
               ("Grufolix", "🐷"), ("Zampomp", "🐇"), ("Piumazzo", "🐔"), ("Coccorix", "🐢"),
               ("Pinnetol", "🐠"), ("Farfallix", "🦋"), ("Formicox", "🐜"), ("Brucalux", "🐛"),
               ("Topignon", "🐁"), ("Paperox", "🦆"), ("Pulcindol", "🐤"), ("Grilletox", "🦗")],
    "Rara": [("Grifospik", "🦔"), ("Mascherox", "🦝"), ("Tassodon", "🦡"), ("Codaflux", "🦦"),
             ("Dentibrek", "🦫"), ("Lupendrax", "🐺"), ("Volpazor", "🦊"), ("Zannivex", "🐗"),
             ("Cornalux", "🦌"), ("Falcorix", "🦅"), ("Gufonyx", "🦉"), ("Fenicort", "🦩"),
             ("Papagalex", "🦜"), ("Serpendrix", "🐍"), ("Ramaross", "🦎")],
    "Epica": [("Macchiazor", "🐆"), ("Tigrendos", "🐅"), ("Leondrak", "🦁"), ("Glacirsus", "🐻‍❄️"),
              ("Rinocerox", "🦏"), ("Gorillith", "🦍"), ("Fangorex", "🐊"), ("Squalidon", "🦈"),
              ("Elefantrix", "🐘"), ("Mammutrex", "🦣")],
    "Leggendaria": [("Ignivorax", "🐉"), ("Purosangue Zeryon", "🦄"), ("Ceneralith", "🐦‍🔥"), ("Abissorax", "🐙")],
    "Divinita": [("Aurumvex Supremo", "👑🐲")],
}
RARITA_BY_NOME = {nome: r for r, lst in CREATURES.items() for nome, _ in lst}

STREAK_BADGES = [(4, "Streak 4 settimane"), (12, "Streak 12 settimane"), (26, "Streak 26 settimane")]
LEVEL_BADGES = [(5, "Livello 5"), (10, "Livello 10"), (20, "Livello 20")]
CHECKIN_BADGES = [(50, "Checkin 50"), (100, "Checkin 100"), (365, "Checkin 365")]

TIPO_LABEL = {"palestra": "Palestra", "camminata": "Camminata"}
WEEKDAY_LABELS = ["L", "M", "M", "G", "V", "S", "D"]


def level_cost(livello: int) -> int:
    return 100 + (livello - 1) * 20


def league_for_level(livello: int) -> str:
    for lo, hi, nome in LEAGUES:
        if livello >= lo and (hi is None or livello <= hi):
            return nome
    return LEAGUES[-1][2]


def _apply_xp_delta(livello: int, xp: int, delta: int) -> tuple[int, int]:
    """Applica un delta xp (positivo o negativo) con salita/discesa di livello a cascata.
    Livello minimo 1, xp minimo 0."""
    xp += delta
    while xp < 0 and livello > 1:
        livello -= 1
        xp += level_cost(livello)
    if xp < 0:
        xp = 0
    while xp >= level_cost(livello):
        xp -= level_cost(livello)
        livello += 1
    return livello, xp


def roll_creature() -> tuple[str, str, str]:
    """Ritorna (nome, emoji, rarita) pescati secondo i pesi di rarità."""
    total = sum(w for _, w in RARITY_WEIGHTS)
    r = random.uniform(0, total)
    upto = 0
    rarita = RARITY_WEIGHTS[-1][0]
    for name, weight in RARITY_WEIGHTS:
        upto += weight
        if r <= upto:
            rarita = name
            break
    nome, emoji = random.choice(CREATURES[rarita])
    return nome, emoji, rarita


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_state(p: dict) -> dict:
    props = p["properties"]

    def _num(key, default=0):
        return props.get(key, {}).get("number") or default

    def _dt(key):
        d = props.get(key, {}).get("date")
        return date.fromisoformat(d["start"][:10]) if d else None

    def _bool(key):
        return bool(props.get(key, {}).get("checkbox"))

    def _multi(key):
        return [o["name"] for o in props.get(key, {}).get("multi_select", [])]

    return {
        "id": p["id"],
        "xp": int(_num("XP")),
        "livello": int(_num("Livello", 1)) or 1,
        "streak": int(_num("StreakSettimane")),
        "scudi": int(_num("Scudi")),
        "totale_checkin": int(_num("TotaleCheckin")),
        "ultimo_checkin": _dt("UltimoCheckin"),
        "penalty_pending": _bool("PenaltyPending"),
        "streak_broken_recently": _bool("StreakBrokenRecently"),
        "creature": _multi("Creature"),
        "badge": _multi("Badge"),
    }


async def _get_state() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_GYMGAME}/query",
            headers=HEADERS, json={"page_size": 1})
    return _parse_state(r.json()["results"][0])


async def _patch_state(page_id: str, properties: dict):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS, json={"properties": properties})


async def _week_checkins(week_start: date) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_GYMCHECKINS}/query",
            headers=HEADERS, json={
                "filter": {"property": "Data", "date": {"on_or_after": week_start.isoformat()}},
                "page_size": 50,
            })
    return r.json().get("results", [])


async def _already_checked_in(oggi: date) -> bool:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_GYMCHECKINS}/query",
            headers=HEADERS, json={
                "filter": {"property": "Data", "date": {"equals": oggi.isoformat()}},
                "page_size": 1,
            })
    return bool(r.json().get("results"))


async def checkin(tipo_raw: str) -> dict:
    tipo = TIPO_LABEL[tipo_raw]
    oggi = datetime.now(ROME).date()
    if await _already_checked_in(oggi):
        return {"text": "Hai già fatto check-in oggi. 💪"}

    state = await _get_state()
    nome, emoji, rarita = roll_creature()
    is_dup = nome in state["creature"]
    xp_gain = XP_CHECKIN + (XP_DUP[rarita] if is_dup else 0)

    nuovo_livello, nuovo_xp = _apply_xp_delta(state["livello"], state["xp"], xp_gain)
    level_up = nuovo_livello > state["livello"]
    nuovi_scudi = state["scudi"]
    shield_unlocked = False
    if level_up and nuovo_livello % SHIELD_EVERY_LEVELS == 0 and nuovi_scudi < SHIELD_MAX:
        nuovi_scudi += 1
        shield_unlocked = True

    nuove_creature = state["creature"] if is_dup else state["creature"] + [nome]
    nuovo_totale = state["totale_checkin"] + 1

    props = {
        "XP": {"number": nuovo_xp},
        "Livello": {"number": nuovo_livello},
        "Scudi": {"number": nuovi_scudi},
        "TotaleCheckin": {"number": nuovo_totale},
        "UltimoCheckin": {"date": {"start": oggi.isoformat()}},
        "Creature": {"multi_select": [{"name": n} for n in nuove_creature]},
    }

    nuovi_badge = list(state["badge"])
    for soglia, badge_nome in CHECKIN_BADGES:
        if nuovo_totale >= soglia and badge_nome not in nuovi_badge:
            nuovi_badge.append(badge_nome)
    for soglia, badge_nome in LEVEL_BADGES:
        if nuovo_livello >= soglia and badge_nome not in nuovi_badge:
            nuovi_badge.append(badge_nome)
    if rarita == "Divinita" and "Leggenda vivente" not in nuovi_badge:
        nuovi_badge.append("Leggenda vivente")
    badge_nuovi = [b for b in nuovi_badge if b not in state["badge"]]
    if nuovi_badge != state["badge"]:
        props["Badge"] = {"multi_select": [{"name": b} for b in nuovi_badge]}

    comeback = state["streak_broken_recently"]
    if comeback:
        props["StreakBrokenRecently"] = {"checkbox": False}

    await _patch_state(state["id"], props)

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_GYMCHECKINS},
            "properties": {
                "Nome": {"title": [{"text": {"content": f"{tipo} {oggi.isoformat()}"}}]},
                "Data": {"date": {"start": oggi.isoformat()}},
                "Tipo": {"select": {"name": tipo}},
                "Creatura": {"rich_text": [{"text": {"content": nome}}]},
                "Rarita": {"select": {"name": rarita}},
            }
        })

    lines = [f"✅ Check-in {tipo.lower()} registrato!"]
    if comeback:
        settimana_corrente = len(await _week_checkins(_week_start(oggi)))
        mancano = max(0, WEEKLY_TARGET - settimana_corrente)
        lines.append(f"\n🙂 Bentornato. Manca {mancano} check-in al prossimo obiettivo settimanale — si riparte da qui.")
    lines.append(f"⭐ XP: {nuovo_xp}/{level_cost(nuovo_livello)} (livello {nuovo_livello})")
    if level_up:
        lines.append(f"🎉 LIVELLO SU! Ora sei livello {nuovo_livello} — Lega {league_for_level(nuovo_livello)}")
    if shield_unlocked:
        lines.append(f"🛡️ Nuovo scudo freeze sbloccato! ({nuovi_scudi}/{SHIELD_MAX})")
    dup_txt = f" — già in collezione, convertito in +{XP_DUP[rarita]}xp" if is_dup else ""
    lines.append(f"\n🎁 Hai trovato: {nome} {emoji} ({rarita.lower()}){dup_txt}")
    for b in badge_nuovi:
        lines.append(f"🏅 Nuovo badge: {b}!")
    return {"text": "\n".join(lines)}


def _bar(pct: float, size: int = 10) -> str:
    filled = max(0, min(size, round(size * pct / 100)))
    return "🟦" * filled + "⬜" * (size - filled)


async def get_status() -> dict:
    state = await _get_state()
    oggi = datetime.now(ROME).date()
    week_start = _week_start(oggi)
    checkins = await _week_checkins(week_start)
    days_done = {date.fromisoformat(c["properties"]["Data"]["date"]["start"][:10]) for c in checkins}

    heatmap_cells = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        if d in days_done:
            cell = "🟩"
        elif d > oggi:
            cell = "⬜"
        else:
            cell = "🟥"
        heatmap_cells.append(f"{WEEKDAY_LABELS[i]}{cell}")

    lega = league_for_level(state["livello"])
    cost = level_cost(state["livello"])
    pct = 100 * state["xp"] / cost if cost else 0

    conteggio = {r: 0 for r in CREATURES}
    for n in state["creature"]:
        r = RARITA_BY_NOME.get(n)
        if r:
            conteggio[r] += 1

    lines = [
        "📊 *Stato Palestra*\n",
        f"⭐ Livello {state['livello']} ({lega}) — {state['xp']}/{cost} xp",
        _bar(pct),
        f"🔥 Streak: {state['streak']} settimane",
        f"🛡️ Scudi freeze: {state['scudi']}/{SHIELD_MAX}",
        f"\n📅 Questa settimana ({len(checkins)}/{WEEKLY_TARGET}):",
        " ".join(heatmap_cells),
        f"\n🎴 Collezione: {len(state['creature'])}/50",
        f"  {conteggio['Comune']} comuni · {conteggio['Rara']} rare · {conteggio['Epica']} epiche · "
        f"{conteggio['Leggendaria']} leggendarie · {conteggio['Divinita']} divinità",
    ]
    if state["badge"]:
        lines.append(f"\n🏅 Badge: {', '.join(state['badge'])}")
    return {"text": "\n".join(lines)}


async def _apply_week_penalty(state: dict) -> dict:
    nuovo_livello, nuovo_xp = _apply_xp_delta(state["livello"], state["xp"], -XP_WEEK_FAIL)
    await _patch_state(state["id"], {
        "XP": {"number": nuovo_xp},
        "Livello": {"number": nuovo_livello},
        "StreakSettimane": {"number": 0},
        "PenaltyPending": {"checkbox": False},
        "StreakBrokenRecently": {"checkbox": True},
    })
    return {"text": f"😔 Obiettivo settimanale non raggiunto. -{XP_WEEK_FAIL}xp, streak azzerata (era {state['streak']})."}


async def evaluate_week() -> dict | None:
    """Chiamata domenica sera: valuta la settimana appena chiusa."""
    oggi = datetime.now(ROME).date()
    week_start = _week_start(oggi)
    count = len(await _week_checkins(week_start))
    state = await _get_state()

    if count >= WEEKLY_TARGET:
        nuovo_streak = state["streak"] + 1
        props = {"StreakSettimane": {"number": nuovo_streak}}
        nuovi_badge = list(state["badge"])
        for soglia, badge_nome in STREAK_BADGES:
            if nuovo_streak >= soglia and badge_nome not in nuovi_badge:
                nuovi_badge.append(badge_nome)
        if count >= OLTRE_OBIETTIVO and "Oltre obiettivo" not in nuovi_badge:
            nuovi_badge.append("Oltre obiettivo")
        badge_nuovi = [b for b in nuovi_badge if b not in state["badge"]]
        if nuovi_badge != state["badge"]:
            props["Badge"] = {"multi_select": [{"name": b} for b in nuovi_badge]}
        await _patch_state(state["id"], props)
        if badge_nuovi:
            return {"text": "\n".join(f"🏅 Nuovo badge: {b}!" for b in badge_nuovi)}
        return None

    if state["scudi"] > 0:
        await _patch_state(state["id"], {"PenaltyPending": {"checkbox": True}})
        n = state["scudi"]
        return {
            "text": (f"😔 Questa settimana: {count}/{WEEKLY_TARGET} — obiettivo non raggiunto.\n\n"
                     f"Hai {n} scud{'o' if n == 1 else 'i'} freeze — salva la streak entro lunedì 23:59."),
            "markup": {"inline_keyboard": [[{"text": "🛡️ Usa scudo", "callback_data": "gs:shield"}]]},
        }
    return await _apply_week_penalty(state)


async def apply_pending_penalty_fallback() -> dict | None:
    """Chiamata lunedì sera: se lo scudo non è stato usato, applica la penalità rimasta in sospeso."""
    state = await _get_state()
    if not state["penalty_pending"]:
        return None
    return await _apply_week_penalty(state)


async def use_shield() -> str:
    state = await _get_state()
    if not state["penalty_pending"]:
        return "Nessuna penalità in sospeso da salvare."
    if state["scudi"] <= 0:
        return "Non hai scudi disponibili."
    nuovi_scudi = state["scudi"] - 1
    await _patch_state(state["id"], {
        "Scudi": {"number": nuovi_scudi},
        "PenaltyPending": {"checkbox": False},
    })
    return f"🛡️ Scudo usato. Streak salva a {state['streak']} settimane. Scudi rimasti: {nuovi_scudi}."


async def friday_nudge() -> str | None:
    oggi = datetime.now(ROME).date()
    count = len(await _week_checkins(_week_start(oggi)))
    if 1 <= count < WEEKLY_TARGET:
        mancano = WEEKLY_TARGET - count
        plurale = "no" if mancano > 1 else ""
        return f"💪 Sei a {count}/{WEEKLY_TARGET} questa settimana — te ne manca{plurale} {mancano} per l'obiettivo. Weekend buono per recuperare."
    return None


async def get_public_status() -> dict:
    """Sottoinsieme non sensibile dello stato gamification, per consumo esterno
    (es. widget portfolio pubblico). Niente creature/badge/dettagli interni."""
    state = await _get_state()
    oggi = datetime.now(ROME).date()
    checkins_settimana = len(await _week_checkins(_week_start(oggi)))
    return {
        "livello": state["livello"],
        "lega": league_for_level(state["livello"]),
        "streak_settimane": state["streak"],
        "checkin_questa_settimana": checkins_settimana,
        "obiettivo_settimanale": WEEKLY_TARGET,
    }
