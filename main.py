"""
Jyotish Dasha Reading API
FastAPI + PyEphem (pure Python, no system deps) + Anthropic AI
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import ephem
import math
import os
import anthropic

app = FastAPI(title="Jyotish Dasha API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Constants ──────────────────────────────────────────────────────────────────

SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
         "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

SIGN_LORDS = {
    "Aries":"Mars","Taurus":"Venus","Gemini":"Mercury","Cancer":"Moon",
    "Leo":"Sun","Virgo":"Mercury","Libra":"Venus","Scorpio":"Mars",
    "Sagittarius":"Jupiter","Capricorn":"Saturn","Aquarius":"Saturn","Pisces":"Jupiter"
}

EXALTATION  = {"Sun":"Aries","Moon":"Taurus","Mars":"Capricorn","Mercury":"Virgo",
               "Jupiter":"Cancer","Venus":"Pisces","Saturn":"Libra","Rahu":"Gemini","Ketu":"Sagittarius"}
DEBILITATION= {"Sun":"Libra","Moon":"Scorpio","Mars":"Cancer","Mercury":"Pisces",
               "Jupiter":"Capricorn","Venus":"Virgo","Saturn":"Aries","Rahu":"Sagittarius","Ketu":"Gemini"}

NAKSHATRAS = [
    ("Ashwini","Ketu"),("Bharani","Venus"),("Krittika","Sun"),
    ("Rohini","Moon"),("Mrigashira","Mars"),("Ardra","Rahu"),
    ("Punarvasu","Jupiter"),("Pushya","Saturn"),("Ashlesha","Mercury"),
    ("Magha","Ketu"),("Purva Phalguni","Venus"),("Uttara Phalguni","Sun"),
    ("Hasta","Moon"),("Chitra","Mars"),("Swati","Rahu"),
    ("Vishakha","Jupiter"),("Anuradha","Saturn"),("Jyeshtha","Mercury"),
    ("Mula","Ketu"),("Purva Ashadha","Venus"),("Uttara Ashadha","Sun"),
    ("Shravana","Moon"),("Dhanishtha","Mars"),("Shatabhisha","Rahu"),
    ("Purva Bhadrapada","Jupiter"),("Uttara Bhadrapada","Saturn"),("Revati","Mercury"),
]

DASHA_YEARS  = {"Ketu":7,"Venus":20,"Sun":6,"Moon":10,"Mars":7,"Rahu":18,"Jupiter":16,"Saturn":19,"Mercury":17}
DASHA_ORDER  = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]

HOUSE_MEANINGS = [
    "self, body, personality","wealth, family, speech","siblings, courage, communication",
    "home, mother, comforts","intelligence, children, past merits","enemies, health, service",
    "spouse, partnerships","longevity, transformation","dharma, luck, father",
    "career, status, public life","gains, social network","losses, moksha, spirituality",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def to_deg(rad):
    return math.degrees(float(rad)) % 360

def get_sign(lon):
    return SIGNS[int(lon / 30)]

def get_planet_info(lon, name):
    sign = get_sign(lon)
    return {
        "longitude": round(lon, 4),
        "sign": sign,
        "degree": round(lon % 30, 2),
        "lord": SIGN_LORDS[sign],
        "exalted": EXALTATION.get(name) == sign,
        "debilitated": DEBILITATION.get(name) == sign,
    }

def get_house(planet_lon, asc_lon):
    diff = (planet_lon - asc_lon) % 360
    return int(diff / 30) + 1

def get_nakshatra_info(moon_lon):
    idx = min(int(moon_lon / 13.3333), 26)
    name, lord = NAKSHATRAS[idx]
    fraction = (moon_lon - idx * 13.3333) / 13.3333
    return name, lord, fraction

def get_dasha_sequence(moon_lon, birth_dt):
    nak_name, dasha_lord, fraction = get_nakshatra_info(moon_lon)
    remaining_years = (1 - fraction) * DASHA_YEARS[dasha_lord]
    start_idx = DASHA_ORDER.index(dasha_lord)
    seq = []
    cur = birth_dt

    def add_yrs(dt, yrs):
        return dt + timedelta(days=yrs * 365.25)

    end = add_yrs(cur, remaining_years)
    seq.append({"planet": dasha_lord, "years": round(remaining_years, 1),
                "start": cur.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")})
    cur = end

    for i in range(1, 9):
        planet = DASHA_ORDER[(start_idx + i) % 9]
        yrs = DASHA_YEARS[planet]
        end = add_yrs(cur, yrs)
        seq.append({"planet": planet, "years": yrs,
                    "start": cur.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")})
        cur = end

    return nak_name, seq

# ── Chart Calculation ──────────────────────────────────────────────────────────

def calculate_chart(bd):
    # Parse birth datetime, convert to UTC
    local_dt = datetime.strptime(f"{bd.dob} {bd.tob}", "%Y-%m-%d %H:%M")
    utc_dt   = local_dt - timedelta(hours=bd.tz_offset)

    # PyEphem observer
    obs = ephem.Observer()
    obs.lat     = str(bd.lat)
    obs.lon     = str(bd.lon)
    obs.date    = utc_dt
    obs.pressure = 0
    obs.epoch   = ephem.J2000

    # Planetary longitudes (heliocentric → ecliptic)
    bodies = {
        "Sun":     ephem.Sun(obs),
        "Moon":    ephem.Moon(obs),
        "Mars":    ephem.Mars(obs),
        "Mercury": ephem.Mercury(obs),
        "Jupiter": ephem.Jupiter(obs),
        "Venus":   ephem.Venus(obs),
        "Saturn":  ephem.Saturn(obs),
    }

    planets = {}
    for name, body in bodies.items():
        lon = to_deg(body.hlong)
        planets[name] = get_planet_info(lon, name)

    # Rahu (mean north node) — approximate
    # Rahu moves ~19.3°/year retrograde from a known position
    j2000 = ephem.Date('2000/1/1 12:00:00')
    days_since_j2000 = float(obs.date) - float(j2000)
    rahu_lon = (125.044522 - (days_since_j2000 * 0.052954)) % 360
    ketu_lon  = (rahu_lon + 180) % 360
    planets["Rahu"] = get_planet_info(rahu_lon, "Rahu")
    planets["Ketu"] = get_planet_info(ketu_lon, "Ketu")

    # Ascendant via sidereal time
    lst_rad  = float(obs.sidereal_time())
    ramc_deg = math.degrees(lst_rad)
    lat_rad  = math.radians(bd.lat)
    eps      = math.radians(23.4397)  # obliquity of ecliptic
    asc_rad  = math.atan2(math.cos(math.radians(ramc_deg)),
                          -(math.sin(math.radians(ramc_deg)) * math.cos(eps)
                            + math.tan(lat_rad) * math.sin(eps)))
    asc_lon  = math.degrees(asc_rad) % 360
    asc_sign = get_sign(asc_lon)
    lagna_lord = SIGN_LORDS[asc_sign]

    # House placements
    for name, pd in planets.items():
        h = get_house(pd["longitude"], asc_lon)
        pd["house"] = h
        pd["house_meaning"] = HOUSE_MEANINGS[h - 1]

    # Nakshatra + Dasha
    moon_lon = planets["Moon"]["longitude"]
    nak_name, dasha_seq = get_dasha_sequence(moon_lon, local_dt)

    today = datetime.now()
    current_dasha = next(
        (d for d in dasha_seq
         if datetime.strptime(d["start"], "%Y-%m-%d") <= today <= datetime.strptime(d["end"], "%Y-%m-%d")),
        dasha_seq[0]
    )

    return {
        "name": bd.name,
        "dob": bd.dob,
        "tob": bd.tob,
        "ascendant": {"longitude": round(asc_lon, 2), "sign": asc_sign,
                      "degree": round(asc_lon % 30, 2), "lord": lagna_lord},
        "planets": planets,
        "nakshatra": nak_name,
        "lagna_lord": lagna_lord,
        "dasha_sequence": dasha_seq,
        "current_dasha": current_dasha,
    }

# ── Prompt Builder ─────────────────────────────────────────────────────────────

def build_prompt(chart):
    p   = chart["planets"]
    asc = chart["ascendant"]
    cur = chart["current_dasha"]

    planet_lines = "\n".join(
        f"  {n}: {d['sign']} {d['degree']}°{'  ★ EXALTED' if d['exalted'] else '  ☆ DEBILITATED' if d['debilitated'] else ''}  — House {d['house']} ({d['house_meaning']})"
        for n, d in p.items()
    )
    dasha_lines = "\n".join(
        f"  {d['planet']}: {d['start']} → {d['end']} ({d['years']} yrs){'  ← CURRENT' if d['planet']==cur['planet'] else ''}"
        for d in chart["dasha_sequence"]
    )

    return f"""You are Jyotish Acharya — a master Vedic astrologer in the classical Parashari tradition.
Write in an authoritative, compassionate, poetic voice. Be specific — reference actual planets, signs, houses, and dasha lords. No generic filler.

BIRTH CHART:
Name: {chart['name']} | DOB: {chart['dob']} | TOB: {chart['tob']}
Ascendant (Lagna): {asc['sign']} {asc['degree']}° — Lagna Lord: {asc['lord']}
Moon Nakshatra: {chart['nakshatra']}

PLANETARY POSITIONS:
{planet_lines}

VIMSHOTTARI DASHA SEQUENCE:
{dasha_lines}

---

Write a comprehensive Jyotish Dasha reading with these exact sections using markdown:

## 1. Chart Overview & Soul Blueprint
- Lagna and lagna lord — core personality and life purpose
- Moon sign and nakshatra — emotional nature and karmic tendencies
- One standout yoga or planetary combination in this chart

## 2. Current Mahadasha: {cur['planet']} ({cur['start']} – {cur['end']})
- Nature and significations of {cur['planet']} and its placement
- **Career & finances** — opportunities, themes, cautions
- **Relationships & emotional life** — what this period activates
- **Health & vitality** — areas to watch
- **Spiritual significance** — the inner invitation of this Mahadasha
- **Key Antardasha windows** — 3 sub-periods with approximate dates and what they bring

## 3. Upcoming Dasha Periods — Life Trajectory
For the next 2 Mahadasha periods after current:
- Major life themes each will bring
- One specific preparation tip for each

## 4. Karmic Patterns — Rahu & Ketu Axis
- Soul's direction this lifetime
- What is being released (Ketu) and reached toward (Rahu)
- Practical guidance for working with the nodal axis

## 5. Remedies & Empowerment
- **Gemstone** — specific recommendation with chart rationale
- **Mantras** — beeja mantra for current Dasha lord + Moon nakshatra mantra (Sanskrit + transliteration + meaning)
- **Daily sadhana** — one practice aligned with current planetary period
- **Seva** — charity aligned with Dasha lord's significations

## 6. Key Timing — Events to Watch (Next 3 Years)
5 specific windows (month + year) when important events are likely. Name the domain (career, relationship, health, spiritual breakthrough, financial). Base on Antardasha shifts.

End with a one-paragraph closing blessing in classical Jyotish style — poetic, affirming, grounded in this chart.
"""

# ── Models ─────────────────────────────────────────────────────────────────────

class BirthData(BaseModel):
    name: str
    dob: str
    tob: str
    lat: float
    lon: float
    tz_offset: float

class ReadingRequest(BaseModel):
    birth_data: BirthData
    anthropic_api_key: Optional[str] = None

# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/chart")
async def get_chart(bd: BirthData):
    try:
        return {"success": True, "chart": calculate_chart(bd)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reading")
async def get_reading(req: ReadingRequest):
    try:
        chart  = calculate_chart(req.birth_data)
        prompt = build_prompt(chart)
        key    = req.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise HTTPException(status_code=400, detail="No API key")
        client  = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return {"success": True, "chart": chart, "reading": message.content[0].text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "engine": "pyephem"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
