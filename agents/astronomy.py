import os
import math
import httpx
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")

# Località supportate. Coordinate approssimate (comune/valle) — per calcoli
# astronomici la differenza di qualche km è trascurabile sull'altezza in gradi.
LOCATIONS = {
    "cormano": {"lat": 45.5387, "lon": 9.1503, "elev": 150, "nome": "Cormano", "meteo": "Milano"},
    "valmalenco": {"lat": 46.2960, "lon": 9.7781, "elev": 1965, "nome": "Alpe Ventina (Rifugio Gerli-Porro)", "meteo": "46.2960,9.7781"},
}
DEFAULT_LOCATION = "cormano"

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


def _observer(location: str = DEFAULT_LOCATION):
    from skyfield.api import wgs84
    _, eph, _ = _load()
    loc = LOCATIONS[location]
    return eph["earth"] + wgs84.latlon(loc["lat"], loc["lon"], elevation_m=loc.get("elev", 0))


def _time_tonight(hour: int = 22):
    """Istante di stasera (oggi, ora locale) alle `hour`, in tempo skyfield."""
    return _time_at(0, hour)


def _time_at(days_ahead: int, hour: int = 22):
    """Istante a `days_ahead` giorni da oggi, ora locale, alle `hour`, in tempo skyfield."""
    _, _, ts = _load()
    now = datetime.now(ROME) + timedelta(days=days_ahead)
    local = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return ts.from_datetime(local)


async def _cloud_cover_forecast(location: str = DEFAULT_LOCATION) -> list[dict]:
    """% copertura nuvolosa (slot 21:00) per i prossimi giorni disponibili da wttr.in (di solito 3)."""
    meteo_query = LOCATIONS[location]["meteo"]
    out = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://wttr.in/{meteo_query}?format=j1", headers={"User-Agent": "curl/7.0"})
        if r.status_code != 200:
            return out
        for day in r.json().get("weather", []):
            cloud = None
            for h in day.get("hourly", []):
                if h.get("time") == "2100":
                    cloud = int(h.get("cloudcover", 50))
            if cloud is not None:
                out.append({"date": day.get("date"), "cloud": cloud})
    except Exception:
        return out
    return out


async def _cloud_cover_tonight(location: str = DEFAULT_LOCATION) -> int | None:
    """% copertura nuvolosa stasera (slot 21:00), via wttr.in — None se non disponibile."""
    forecast = await _cloud_cover_forecast(location)
    return forecast[0]["cloud"] if forecast else None


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


def _visible_planets(t, location: str = DEFAULT_LOCATION) -> list[dict]:
    observer = _observer(location)
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


def _moon_distance_km(t, location: str = DEFAULT_LOCATION) -> float:
    observer = _observer(location)
    _, eph, _ = _load()
    astrometric = observer.at(t).observe(eph["moon"]).apparent()
    return astrometric.distance().km


def _venus_elongation(t, location: str = DEFAULT_LOCATION) -> float:
    observer = _observer(location)
    _, eph, _ = _load()
    v = observer.at(t).observe(eph["venus"]).apparent()
    s = observer.at(t).observe(eph["sun"]).apparent()
    return v.separation_from(s).degrees


def _planet_conjunctions(t, location: str = DEFAULT_LOCATION) -> list[str]:
    """Coppie di pianeti separati meno di 3° in cielo — evento notevole a occhio nudo/binocolo."""
    observer = _observer(location)
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

async def get_tonight_sky(location: str = DEFAULT_LOCATION) -> str:
    """Cosa vedere stasera con un Mak 90: meteo, fase lunare, pianeti visibili."""
    nome = LOCATIONS[location]["nome"]
    t = _time_tonight()
    cloud = await _cloud_cover_tonight(location)
    moon = _moon_phase(t)
    planets = _visible_planets(t, location)

    lines = [f"🔭 *Cielo stasera da {nome}*\n"]

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
        lines.append("🪐 *Pianeti stasera:*")
        for p in planets:
            quota = "buona quota" if p["buona_quota"] else "basso sull'orizzonte, turbolenza"
            lines.append(f"• *{p['nome']}* ({p['alt']}°, {quota}) — {p['nota']}")
    else:
        lines.append("Nessun pianeta a quota utile stasera per il Mak 90.")

    shower = _meteor_shower_today()
    if shower:
        lines.append(f"\n{shower}")

    return "\n".join(lines)


async def get_best_night(location: str = DEFAULT_LOCATION) -> str:
    """Tra i giorni disponibili in previsione (di solito 3), qual è la serata migliore
    per osservare — utile quando stasera è coperto ma tra 2 giorni potrebbe schiarirsi."""
    nome = LOCATIONS[location]["nome"]
    forecast = await _cloud_cover_forecast(location)
    if not forecast:
        return "Previsioni meteo non disponibili al momento."

    best = min(forecast, key=lambda d: d["cloud"])
    idx = forecast.index(best)
    t = _time_at(idx)
    moon = _moon_phase(t)

    giorno = "stasera" if idx == 0 else ("domani sera" if idx == 1 else f"tra {idx} giorni ({best['date']})")

    lines = [f"🔭 *Prossima serata migliore da {nome}: {giorno}*\n"]
    if best["cloud"] < 30:
        lines.append(f"☀️ {best['cloud']}% nuvole previste — buona finestra di osservazione")
    elif best["cloud"] < 70:
        lines.append(f"⛅ {best['cloud']}% nuvole previste — la migliore disponibile, ma incerta")
    else:
        lines.append(f"☁️ Anche la migliore serata dei prossimi giorni è coperta ({best['cloud']}% nuvole)")
    lines.append(f"🌙 {moon['name']} ({moon['illum']:.0f}% illuminata) quella sera")

    others = [d for d in forecast if d is not best]
    if others:
        lines.append("\nAltri giorni:")
        for d in others:
            i = forecast.index(d)
            label = "stasera" if i == 0 else ("domani" if i == 1 else f"tra {i}gg")
            lines.append(f"• {label}: {d['cloud']}% nuvole")

    return "\n".join(lines)


async def check_exceptional_events(location: str = DEFAULT_LOCATION) -> str | None:
    """Controllo proattivo (1x/giorno): ritorna un messaggio SOLO se c'è un evento
    notevole stanotte E il cielo è sereno — altrimenti None (nessun avviso)."""
    cloud = await _cloud_cover_tonight(location)
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
        dist = _moon_distance_km(t, location)
        if dist < 362000:
            events.append(f"🌕 Superluna stanotte (distanza {dist:.0f}km, piena vicino al perigeo)")

    elong = _venus_elongation(t, location)
    if elong > 44:
        events.append(f"✨ Venere alla massima elongazione ({elong:.1f}°) — massima visibilità")

    events.extend(f"🪐 {c}" for c in _planet_conjunctions(t, location))

    if not events:
        return None
    return "🔭 *Evento astronomico stanotte* (cielo sereno)\n\n" + "\n".join(events)
