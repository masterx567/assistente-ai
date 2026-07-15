import os
import math
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")

# Cormano (Milano nord) — coordinate del comune, non serve l'indirizzo esatto
# per calcoli astronomici (differenza trascurabile su scala di gradi).
LAT, LON = 45.5387, 9.1503

# skyfield scarica un file effemeridi (~17MB) al primo uso — su Vercel il
# filesystem è read-only tranne /tmp, quindi la cache va forzata lì (stesso
# problema/fix già visto con matplotlib in questo stesso progetto).
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
_SKYFIELD_DIR = "/tmp/skyfield"

_PLANETS_IT = {
    "Mercurio": "mercury",
    "Venere": "venus",
    "Marte": "mars",
    "Giove": "jupiter barycenter",
    "Saturno": "saturn barycenter",
}

# Soglia minima altezza (gradi) e nota pratica per un Mak 90 (90mm, f/13-14, ~1250mm focale):
# a bassa quota la turbolenza atmosferica vanifica la risoluzione di un rifrattore/Mak,
# quindi la soglia "tecnicamente sopra l'orizzonte" (10°) non basta per capire se ha senso puntarlo.
_PLANET_INFO = {
    "Mercurio": {"min_alt": 20, "note": "difficile anche con cielo terso, solo la fase (a spicchio)"},
    "Venere": {"min_alt": 10, "note": "solo fase (a spicchio), nessun dettaglio di superficie visibile"},
    "Marte": {"min_alt": 15, "note": "dettagli solo vicino all'opposizione, altrimenti disco piccolo"},
    "Giove": {"min_alt": 10, "note": "bande nuvolose e 4 lune galileiane visibili, prova 80-120x"},
    "Saturno": {"min_alt": 10, "note": "anelli ben visibili, prova 100-150x"},
}

# Piogge di stelle cadenti: date di picco fisse ogni anno (legate alla posizione
# orbitale terrestre, non cambiano da un anno all'altro se non di ±1 giorno).
METEOR_SHOWERS = [
    ("Quadrantidi", 1, 3),
    ("Liridi", 4, 22),
    ("Eta Acquaridi", 5, 5),
    ("Perseidi", 8, 12),
    ("Orionidi", 10, 21),
    ("Leonidi", 11, 17),
    ("Geminidi", 12, 13),
    ("Ursidi", 12, 22),
]

_loader = None
_eph = None
_ts = None


def _load():
    """Carica skyfield + effemeridi (lazy, cache in /tmp, riusata tra chiamate sulla stessa istanza)."""
    global _loader, _eph, _ts
    if _eph is None:
        from skyfield.api import Loader
        os.makedirs(_SKYFIELD_DIR, exist_ok=True)
        _loader = Loader(_SKYFIELD_DIR)
        _ts = _loader.timescale()
        _eph = _loader("de421.bsp")
    return _loader, _eph, _ts


def _observer():
    from skyfield.api import wgs84
    _, eph, _ = _load()
    return eph["earth"] + wgs84.latlon(LAT, LON)


def _time_tonight(hour: int = 22):
    """Istante di stasera (oggi, ora locale Cormano) alle `hour`, in tempo skyfield."""
    _, _, ts = _load()
    now = datetime.now(ROME)
    local = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return ts.from_datetime(local)


async def _cloud_cover_tonight() -> int | None:
    """% copertura nuvolosa stasera (slot 21:00), via wttr.in — None se non disponibile."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://wttr.in/Milano?format=j1", headers={"User-Agent": "curl/7.0"})
        if r.status_code != 200:
            return None
        day = r.json()["weather"][0]
        for h in day["hourly"]:
            if h.get("time") == "2100":
                return int(h.get("cloudcover", 50))
    except Exception:
        return None
    return None


def _moon_phase(t) -> dict:
    from skyfield import almanac
    _, eph, _ = _load()
    angle = almanac.moon_phase(eph, t).degrees
    illum = (1 - math.cos(math.radians(angle))) / 2 * 100
    if illum < 2:
        name = "Luna nuova"
    elif illum > 98:
        name = "Luna piena"
    elif angle < 180:
        name = "Luna crescente"
    else:
        name = "Luna calante"
    return {"illum": illum, "name": name, "angle": angle}


def _visible_planets(t) -> list[dict]:
    observer = _observer()
    _, eph, _ = _load()
    out = []
    for name_it, key in _PLANETS_IT.items():
        astrometric = observer.at(t).observe(eph[key]).apparent()
        alt, az, _ = astrometric.altaz()
        info = _PLANET_INFO[name_it]
        if alt.degrees > info["min_alt"]:
            out.append({
                "nome": name_it, "alt": round(alt.degrees), "az": round(az.degrees),
                "nota": info["note"], "buona_quota": alt.degrees >= 30,
            })
    return sorted(out, key=lambda p: -p["alt"])


def _moon_distance_km(t) -> float:
    observer = _observer()
    _, eph, _ = _load()
    astrometric = observer.at(t).observe(eph["moon"]).apparent()
    return astrometric.distance().km


def _venus_elongation(t) -> float:
    observer = _observer()
    _, eph, _ = _load()
    v = observer.at(t).observe(eph["venus"]).apparent()
    s = observer.at(t).observe(eph["sun"]).apparent()
    return v.separation_from(s).degrees


def _planet_conjunctions(t) -> list[str]:
    """Coppie di pianeti separati meno di 3° in cielo — evento notevole a occhio nudo/binocolo."""
    observer = _observer()
    _, eph, _ = _load()
    positions = {}
    for name_it, key in _PLANETS_IT.items():
        positions[name_it] = observer.at(t).observe(eph[key]).apparent()
    names = list(positions.keys())
    out = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sep = positions[names[i]].separation_from(positions[names[j]]).degrees
            if sep < 3:
                out.append(f"{names[i]} e {names[j]} vicini in cielo ({sep:.1f}°)")
    return out


def _meteor_shower_today() -> str | None:
    today = datetime.now(ROME).date()
    for name, month, day in METEOR_SHOWERS:
        if today.month == month and abs(today.day - day) <= 1:
            return f"🌠 Picco pioggia di stelle cadenti: *{name}*"
    return None


# ── API pubblica ──────────────────────────────────────────────────────────────

async def get_tonight_sky() -> str:
    """Cosa vedere stasera da Cormano con un Mak 90: meteo, fase lunare, pianeti visibili."""
    t = _time_tonight()
    cloud = await _cloud_cover_tonight()
    moon = _moon_phase(t)
    planets = _visible_planets(t)

    lines = ["🔭 *Cielo stasera da Cormano*\n"]

    if cloud is not None:
        if cloud < 30:
            lines.append(f"☀️ Cielo sereno stasera ({cloud}% nuvole) — buona serata per osservare")
        elif cloud < 70:
            lines.append(f"⛅ Cielo parzialmente coperto ({cloud}% nuvole) — osservazione incerta")
        else:
            lines.append(f"☁️ Cielo molto coperto ({cloud}% nuvole) — sconsigliato uscire col telescopio")
        lines.append("")

    lines.append(f"🌙 {moon['name']} ({moon['illum']:.0f}% illuminata)")
    lines.append("")

    if planets:
        lines.append("🪐 *Pianeti — cosa vale la pena col Mak 90 stasera:*")
        for p in planets:
            quota = "buona quota" if p["buona_quota"] else "basso, aspettati turbolenza"
            lines.append(f"  • *{p['nome']}* — {p['alt']}° ({quota})\n    {p['nota']}")
    else:
        lines.append("Nessun pianeta a quota utile stasera per il Mak 90.")

    shower = _meteor_shower_today()
    if shower:
        lines.append(f"\n{shower}")

    return "\n".join(lines)


async def check_exceptional_events() -> str | None:
    """Controllo proattivo (1x/giorno): ritorna un messaggio SOLO se c'è un evento
    notevole stanotte E il cielo è sereno — altrimenti None (nessun avviso)."""
    cloud = await _cloud_cover_tonight()
    if cloud is None or cloud >= 30:
        return None

    t = _time_tonight()
    events = []

    shower = _meteor_shower_today()
    if shower:
        events.append(shower)

    moon = _moon_phase(t)
    if moon["illum"] < 2:
        events.append("🌑 Luna nuova stanotte — cielo scuro, momento migliore per il deep-sky")
    elif moon["illum"] > 98:
        dist = _moon_distance_km(t)
        if dist < 362000:
            events.append(f"🌕 Superluna stanotte (distanza {dist:.0f}km, piena vicino al perigeo)")

    elong = _venus_elongation(t)
    if elong > 44:
        events.append(f"✨ Venere alla massima elongazione ({elong:.1f}°) — massima visibilità")

    events.extend(f"🪐 {c}" for c in _planet_conjunctions(t))

    if not events:
        return None
    return "🔭 *Evento astronomico stanotte* (cielo sereno)\n\n" + "\n".join(events)
