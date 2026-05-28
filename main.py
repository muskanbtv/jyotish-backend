"""
Jyotish Dasha Reading API
FastAPI backend: Swiss Ephemeris chart calculation + Anthropic AI reading
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional
import swisseph as swe
import anthropic
import math
import os

app = FastAPI(title="Jyotish Dasha API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

swe.set_ephe_path('')  # Use built-in Moshier ephemeris — no external files needed

# ── Constants ─────────────────────────────────────────────────────────────────

SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

NAKSHATRAS = [
    ("Ashwini","Ketu",0),("Bharani","Venus",13.333),("Krittika","Sun",26.667),
    ("Rohini","Moon",40),("Mrigashira","Mars",53.333),("Ardra","Rahu",66.667),
    ("Punarvasu","Jupiter",80),("Pushya","Saturn",93.333),("Ashlesha","Mercury",106.667),
    ("Magha","Ketu",120),("Purva Phalguni","Venus",133.333),("Uttara Phalguni","Sun",146.667),
    ("Hasta","Moon",160),("Chitra","Mars",173.333),("Swati","Rahu",186.667),
    ("Vishakha","Jupiter",200),("Anuradha","Saturn",213.333),("Jyeshtha","Mercury",226.667),
    ("Mula","Ketu",240),("Purva Ashadha","Venus",253.333),("Uttara Ashadha","Sun",266.667),
    ("Shravana","Moon",280),("Dhanishtha","Mars",293.333),("Shatabhisha","Rahu",306.667),
    ("Purva Bhadrapada","Jupiter",320),("Uttara Bhadrapada","Saturn",333.333),("Revati","Mercury",346.667),
]

DASHA_YEARS = {
    "Ketu":7,"Venus":20,"Sun":6,"Moon":10,"Mars":7,
    "Rahu":18,"Jupiter":16,"Saturn":19,"Mercury":17
}

DASHA_ORDER = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]

PLANET_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS,
    "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS, "Saturn": swe.SATURN
}

RAHU_KETU_CORRECTION = True  # Mean node

HOUSE_MEANINGS = [
    "self, body, personality",
    "wealth, family, speech",
    "siblings, courage, communication",
    "home, mother, comforts",
    "intelligence, children, past merits",
    "enemies, health, service, debts",
    "spouse, partnerships, business",
    "longevity, transformation, hidden matters",
    "dharma, higher learning, father, luck",
    "career, status, government, public life",
    "gains, elder siblings, social network",
    "losses, moksha, foreign lands, spirituality",
]

SIGN_LORDS = {
    "Aries":"Mars","Taurus":"Venus","Gemini":"Mercury","Cancer":"Moon",
    "Leo":"Sun","Virgo":"Mercury","Libra":"Venus","Scorpio":"Mars",
    "Sagittarius":"Jupiter","Capricorn":"Saturn","Aquarius":"Saturn","Pisces":"Jupiter"
}

EXALTATION = {
    "Sun":"Aries","Moon":"Taurus","Mars":"Capricorn","Mercury":"Virgo",
    "Jupiter":"Cancer","Venus":"Pisces","Saturn":"Libra",
    "Rahu":"Gemini","Ketu":"Sagittarius"
}

DEBILITATION = {
    "Sun":"Libra","Moon":"Scorpio","Mars":"Cancer","Mercury":"Pisces",
    "Jupiter":"Capricorn","Venus":"Virgo","Saturn":"Aries",
    "Rahu":"Sagittarius","Ketu":"Gemini"
}

# ── Pydantic models ───────────────────────────────────────────────────────────

class BirthData(BaseModel):
    name: str
    dob: str          # YYYY-MM-DD
    tob: str          # HH:MM  (24hr, local time)
    lat: float        # latitude
    lon: float        # longitude
    tz_offset: float  # hours from UTC, e.g. 5.5 for IST

class ReadingRequest(BaseModel):
    birth_data: BirthData
    anthropic_api_key: Optional[str] = None  # passed from frontend env

# ── Chart Calculation ─────────────────────────────────────────────────────────

def get_nakshatra(moon_lon: float):
    idx = int(moon_lon / 13.333333)
    idx = min(idx, 26)
    name, lord, start = NAKSHATRAS[idx]
    fraction = (moon_lon - start) / 13.333333
    return name, lord, fraction

def get_dasha_sequence(moon_lon: float, birth_dt: datetime):
    nakshatra, dasha_lord, fraction = get_nakshatra(moon_lon)
    remaining_fraction = 1.0 - fraction
    remaining_years = remaining_fraction * DASHA_YEARS[dasha_lord]

    start_idx = DASHA_ORDER.index(dasha_lord)
    sequence = []
    current_date = birth_dt

    # First partial dasha
    end_date = datetime(
        current_date.year + int(remaining_years),
        current_date.month,
        current_date.day
    )
    sequence.append({
        "planet": dasha_lord,
        "years": round(remaining_years, 2),
        "start": current_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d"),
        "partial": True
    })
    current_date = end_date

    # Full dashas
    for i in range(1, 9):
        planet = DASHA_ORDER[(start_idx + i) % 9]
        years = DASHA_YEARS[planet]
        # Approximate end date
        total_days = int(years * 365.25)
        from datetime import timedelta
        end_date = current_date + timedelta(days=total_days)
        sequence.append({
            "planet": planet,
            "years": years,
            "start": current_date.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d"),
            "partial": False
        })
        current_date = end_date

    return nakshatra, sequence

def calculate_chart(bd: BirthData) -> dict:
    # Parse datetime, convert to UTC
    dt_str = f"{bd.dob} {bd.tob}"
    local_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    utc_hour = local_dt.hour + local_dt.minute/60.0 - bd.tz_offset
    jd = swe.julday(local_dt.year, local_dt.month, local_dt.day, utc_hour)

    # Planet positions
    planets = {}
    for pname, pid in PLANET_IDS.items():
        pos, _ = swe.calc_ut(jd, pid)
        lon = pos[0]
        sign = SIGNS[int(lon / 30)]
        degree = lon % 30
        planets[pname] = {
            "longitude": round(lon, 4),
            "sign": sign,
            "degree": round(degree, 2),
            "lord": SIGN_LORDS[sign],
            "exalted": EXALTATION.get(pname) == sign,
            "debilitated": DEBILITATION.get(pname) == sign,
        }

    # Rahu/Ketu (mean nodes)
    node_pos, _ = swe.calc_ut(jd, swe.MEAN_NODE)
    rahu_lon = node_pos[0]
    ketu_lon = (rahu_lon + 180) % 360
    for pname, lon in [("Rahu", rahu_lon), ("Ketu", ketu_lon)]:
        sign = SIGNS[int(lon / 30)]
        planets[pname] = {
            "longitude": round(lon, 4),
            "sign": sign,
            "degree": round(lon % 30, 2),
            "lord": SIGN_LORDS[sign],
            "exalted": EXALTATION.get(pname) == sign,
            "debilitated": DEBILITATION.get(pname) == sign,
        }

    # Ascendant + houses
    houses_cusps, ascmc = swe.houses(jd, bd.lat, bd.lon, b'P')
    asc_lon = ascmc[0]
    asc_sign = SIGNS[int(asc_lon / 30)]
    lagna_lord = SIGN_LORDS[asc_sign]

    # House placements for each planet
    house_list = list(houses_cusps)
    for pname, pdata in planets.items():
        lon = pdata["longitude"]
        house = 1
        for i in range(12):
            cusp_start = house_list[i]
            cusp_end = house_list[(i + 1) % 12]
            if cusp_end < cusp_start:
                cusp_end += 360
            plon = lon if lon >= cusp_start else lon + 360
            if cusp_start <= plon < cusp_end:
                house = i + 1
                break
        planets[pname]["house"] = house
        planets[pname]["house_meaning"] = HOUSE_MEANINGS[house - 1]

    # Moon nakshatra + dasha sequence
    moon_lon = planets["Moon"]["longitude"]
    nakshatra, dasha_seq = get_dasha_sequence(moon_lon, local_dt)

    # Current dasha
    today = datetime.now()
    current_dasha = None
    for d in dasha_seq:
        if datetime.strptime(d["start"], "%Y-%m-%d") <= today <= datetime.strptime(d["end"], "%Y-%m-%d"):
            current_dasha = d
            break

    return {
        "name": bd.name,
        "dob": bd.dob,
        "tob": bd.tob,
        "place": f"lat {bd.lat}, lon {bd.lon}",
        "ascendant": {
            "longitude": round(asc_lon, 2),
            "sign": asc_sign,
            "degree": round(asc_lon % 30, 2),
            "lord": lagna_lord,
        },
        "planets": planets,
        "nakshatra": nakshatra,
        "lagna_lord": lagna_lord,
        "dasha_sequence": dasha_seq,
        "current_dasha": current_dasha,
        "house_cusps": [round(h, 2) for h in houses_cusps],
    }

# ── Prompt Builder ────────────────────────────────────────────────────────────

def build_prompt(chart: dict) -> str:
    p = chart["planets"]
    asc = chart["ascendant"]
    dashas = chart["dasha_sequence"]
    cur = chart["current_dasha"]

    planet_lines = []
    for pname, pd in p.items():
        status = ""
        if pd["exalted"]: status = " (EXALTED)"
        if pd["debilitated"]: status = " (DEBILITATED)"
        planet_lines.append(
            f"  {pname}: {pd['sign']} {pd['degree']}°{status}, House {pd['house']} ({pd['house_meaning']})"
        )

    dasha_lines = []
    for d in dashas:
        tag = " ← CURRENT" if cur and d["planet"] == cur["planet"] else ""
        dasha_lines.append(f"  {d['planet']}: {d['start']} to {d['end']} ({d['years']} yrs){tag}")

    return f"""You are Jyotish Acharya — a master Vedic astrologer trained in the classical Parashari tradition. 
You write in an authoritative yet compassionate voice — precise, poetic, and deeply personalised.
Never use generic filler. Every sentence must draw on the actual chart data provided.

BIRTH CHART DATA:
Name: {chart['name']}
Date of Birth: {chart['dob']}
Time of Birth: {chart['tob']}
Ascendant (Lagna): {asc['sign']} {asc['degree']}° — Lagna Lord: {asc['lord']}
Moon Nakshatra: {chart['nakshatra']}

PLANETARY POSITIONS:
{chr(10).join(planet_lines)}

VIMSHOTTARI DASHA SEQUENCE:
{chr(10).join(dasha_lines)}

---

Write a comprehensive Jyotish Dasha reading for {chart['name']} covering ALL of the following sections.
Use markdown formatting with clear section headers. Be specific — reference actual planets, signs, houses, and dasha lords.

1. **Chart Overview & Soul Blueprint**
   - Lagna, lagna lord placement, and what this gives the native as a core personality
   - Moon sign and nakshatra — the emotional nature and karmic tendencies
   - One standout planetary yoga or combination visible in this chart

2. **Current Mahadasha: {cur['planet'] if cur else 'Analysis'} ({cur['start'] if cur else ''} – {cur['end'] if cur else ''})**
   - The nature of this Dasha lord and its placement in the chart
   - Career & finances: specific themes, opportunities, cautions
   - Relationships & emotional life: what this period activates
   - Health & vitality: areas to watch, constitutional tendencies
   - Spiritual significance: inner growth themes for this period
   - Key timing windows: 2–3 specific sub-period (Antardasha) shifts to watch within this Mahadasha, with approximate dates

3. **Upcoming Dasha Periods — Life Trajectory**
   For the next 2 upcoming Mahadasha periods (after current):
   - Brief but meaningful description of what each period will bring
   - Major life themes: career pivots, relationship developments, relocations, spiritual shifts
   - One specific piece of guidance for preparing now

4. **Karmic Patterns & Past Life Imprints**
   - Rahu and Ketu axis: the karmic direction of this lifetime
   - What the soul is releasing (Ketu) and reaching toward (Rahu)
   - How the nodal placement manifests in practical life

5. **Remedies & Empowerment**
   - Gemstone recommendation (with rationale from chart)
   - Mantras: specific mantras for the current Dasha lord and lagna lord (Sanskrit with transliteration)
   - Pratical sadhana: one daily practice aligned with the current planetary period
   - Charity / seva recommendation aligned with Dasha lord

6. **Key Timing — Events to Watch**
   Give 4–5 specific windows (month + year) in the next 3 years when important life events are likely, and what domain (career, relationship, health, spiritual breakthrough, financial). Base these on Antardasha periods and transits.

End with a one-paragraph closing blessing in the style of classical Jyotish — poetic, affirming, grounded in the chart.
"""

# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/chart")
async def get_chart(bd: BirthData):
    """Return raw chart data (free)"""
    try:
        chart = calculate_chart(bd)
        return {"success": True, "chart": chart}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reading")
async def get_reading(req: ReadingRequest):
    """Generate full AI reading (paid)"""
    try:
        chart = calculate_chart(req.birth_data)
        prompt = build_prompt(chart)

        api_key = req.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="No API key provided")

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        reading_text = message.content[0].text
        return {
            "success": True,
            "chart": chart,
            "reading": reading_text,
            "tokens_used": message.usage.input_tokens + message.usage.output_tokens
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "ephe": "swiss"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
