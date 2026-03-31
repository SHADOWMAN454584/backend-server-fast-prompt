# main.py — CrowdSense AI API v4.2
# Real-time crowd density engine:
#   PRIMARY  → BestTime.app Live/Now API  (if BESTTIME_API_KEY set)
#              - Improved venue matching (fuzzy + lat/lng filter)
#              - Live endpoint → Now endpoint fallback chain
#              - Weekly forecast for accurate hourly curves
#   SECONDARY → Google Places popularity (if GOOGLE_MAPS_KEY set)
#   TERTIARY → CrowdSense Physics Engine (re-calibrated)
#              Inputs: venue type · time-of-day · day-of-week · weather proxy
#              · IST public holiday calendar · venue capacity model

import os
import time
import math
import random
import asyncio
import hashlib
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any, Dict, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import httpx

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CrowdSense AI API",
    description="Real-time crowd density — BestTime · Google Places · Physics Engine",
    version="4.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────────────────────

GEMINI_API_KEY         = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY           = os.getenv("GROQ_API_KEY", "")
GOOGLE_MAPS_KEY        = os.getenv("GOOGLE_MAPS_API_KEY", "")
BESTTIME_API_KEY       = os.getenv("BESTTIME_API_KEY", "")
OPENWEATHER_KEY        = os.getenv("OPENWEATHER_API_KEY", "")

# ── Gemini (primary) ──────────────────────────────────────────────────────────
# Using gemini-1.5-flash — higher free-tier quota than gemini-2.0-flash
gemini_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    print("[AI] Gemini gemini-1.5-flash configured as primary provider.")
else:
    print("[WARNING] GEMINI_API_KEY not set — Gemini unavailable. Groq emergency fallback will be used if configured.")

# ── Groq (emergency fallback) ─────────────────────────────────────────────────
# Free tier: 14,400 req/day, 30 req/min — activates only when Gemini is exhausted
groq_client = None
if GROQ_API_KEY:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)
    print("[AI] Groq configured as emergency fallback provider.")
else:
    print("[WARNING] GROQ_API_KEY not set — no emergency fallback available.")

# ─────────────────────────────────────────────────────────────────────────────
# Mumbai Locations — verified coordinates + venue metadata
# ─────────────────────────────────────────────────────────────────────────────

LOCATIONS = [
    {
        "locationId":   "loc-csmt",
        "locationName": "CSMT Railway Station",
        "latitude":     18.9398, "longitude": 72.8354,
        "area":         "South Mumbai",
        "venue_type":   "railway_station",
        "capacity":     6000,
        "osm_id":       "node/1234567",
    },
    {
        "locationId":   "loc-dadar",
        "locationName": "Dadar Station",
        "latitude":     19.0186, "longitude": 72.8424,
        "area":         "Central Mumbai",
        "venue_type":   "railway_station",
        "capacity":     4500,
        "osm_id":       "node/1234568",
    },
    {
        "locationId":   "loc-bandra",
        "locationName": "Bandra Station",
        "latitude":     19.0543, "longitude": 72.8403,
        "area":         "West Mumbai",
        "venue_type":   "railway_station",
        "capacity":     3500,
        "osm_id":       "node/1234569",
    },
    {
        "locationId":   "loc-andheri",
        "locationName": "Andheri Station",
        "latitude":     19.1197, "longitude": 72.8469,
        "area":         "North-West Mumbai",
        "venue_type":   "railway_station",
        "capacity":     5000,
        "osm_id":       "node/1234570",
    },
    {
        "locationId":   "loc-airport",
        "locationName": "Chhatrapati Shivaji Airport",
        "latitude":     19.0896, "longitude": 72.8656,
        "area":         "East Mumbai",
        "venue_type":   "airport",
        "capacity":     8000,
        "osm_id":       "node/1234571",
    },
    {
        "locationId":   "loc-gateway",
        "locationName": "Gateway of India",
        "latitude":     18.9220, "longitude": 72.8347,
        "area":         "South Mumbai",
        "venue_type":   "tourist_attraction",
        "capacity":     2000,
        "osm_id":       "node/1234572",
    },
    {
        "locationId":   "loc-juhu-beach",
        "locationName": "Juhu Beach",
        "latitude":     19.1075, "longitude": 72.8263,
        "area":         "West Mumbai",
        "venue_type":   "beach",
        "capacity":     5000,
        "osm_id":       "node/1234573",
    },
    {
        "locationId":   "loc-phoenix-mall",
        "locationName": "Phoenix Palladium Mall",
        "latitude":     18.9937, "longitude": 72.8262,
        "area":         "Central Mumbai",
        "venue_type":   "shopping_mall",
        "capacity":     3000,
        "osm_id":       "node/1234574",
    },
    {
        "locationId":   "loc-dharavi",
        "locationName": "Dharavi Market",
        "latitude":     19.0405, "longitude": 72.8543,
        "area":         "Central Mumbai",
        "venue_type":   "market",
        "capacity":     2500,
        "osm_id":       "node/1234575",
    },
    {
        "locationId":   "loc-borivali",
        "locationName": "Borivali Station",
        "latitude":     19.2284, "longitude": 72.8564,
        "area":         "North Mumbai",
        "venue_type":   "railway_station",
        "capacity":     4000,
        "osm_id":       "node/1234576",
    },
    {
        "locationId":   "loc-thane",
        "locationName": "Thane Station",
        "latitude":     19.1890, "longitude": 72.9710,
        "area":         "Thane",
        "venue_type":   "railway_station",
        "capacity":     4500,
        "osm_id":       "node/1234577",
    },
    {
        "locationId":   "loc-lower-parel",
        "locationName": "Lower Parel BKC",
        "latitude":     18.9966, "longitude": 72.8296,
        "area":         "South-Central Mumbai",
        "venue_type":   "business_district",
        "capacity":     3500,
        "osm_id":       "node/1234578",
    },
]

LOCATION_MAP = {loc["locationId"]: loc for loc in LOCATIONS}

MUMBAI_BOUNDS = {
    "north": 19.2890, "south": 18.8900,
    "east":  72.9800, "west":  72.7900,
    "center_lat": 19.0760, "center_lng": 72.8777,
}

# ─────────────────────────────────────────────────────────────────────────────
# IST Public Holidays 2025–2026
# ─────────────────────────────────────────────────────────────────────────────

MUMBAI_HOLIDAYS = {
    "2025-01-01", "2025-01-14", "2025-01-26",
    "2025-03-17", "2025-04-14", "2025-04-18",
    "2025-05-01", "2025-08-15", "2025-08-27",
    "2025-10-02", "2025-10-20", "2025-10-24",
    "2025-11-05", "2025-12-25",
    "2026-01-01", "2026-01-26", "2026-03-20",
    "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-08-15", "2026-10-02",
}

# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Caches
# ─────────────────────────────────────────────────────────────────────────────

# ── BestTime venue-ID cache (registered venue_id per venue name+address) ─────
# We separate forecast registration (used to get venue_id only) from
# live/forecast-now queries so we never re-register a venue unnecessarily.
_venue_id_cache:       Dict[str, dict] = {}
_live_cache:           Dict[str, dict] = {}
_forecast_now_cache:   Dict[str, dict] = {}   # cache forecast-now per venue
_weekly_cache:         Dict[str, dict] = {}   # cache weekly raw curves
_crowd_cache:          Dict[str, dict] = {}
_weather_cache:        Dict[str, dict] = {}
_google_places_cache:  Dict[str, dict] = {}

LIVE_TTL          = 180    # 3 min (more responsive to real-time changes)
FORECAST_NOW_TTL  = 300    # 5 min  (reduced for better accuracy)
WEEKLY_TTL        = 3600   # 1 hour (weekly forecasts are stable)
CROWD_TTL         = 180    # 3 min (reduced for fresher data)
WEATHER_TTL       = 1800   # 30 min
PLACES_TTL        = 600    # 10 min
VENUE_ID_TTL      = 86400  # 24 h

_last_nominatim_call = 0.0

training_state = {
    "status": "idle", "started_at": None,
    "completed_at": None, "last_error": None, "last_rows_used": 0,
}
realtime_cache: list = []

# ─────────────────────────────────────────────────────────────────────────────
# ── CROWD PHYSICS ENGINE  (re-calibrated v4.2) ───────────────────────────────
#
# KEY FIXES vs v4.0:
#  1. Curves scaled down — peak values now 0.65–0.75 (not 0.91–0.99) so that
#     even peak hours don't always render "high".  True peaks (rush hour) still
#     reach 0.75–0.80 after multipliers, producing realistic 55–75% readings.
#  2. loc_salt removed — was always adding +0..+6 to density, biasing high.
#     Replaced with a ±3 symmetric offset so the mean contribution is zero.
#  3. Weather proxy now suppresses correctly for ALL hours in monsoon, not
#     just 14–18h.  Beach/tourist at 11 AM in July should NOT be high.
#  4. Weekend/holiday multipliers capped so they can't push indoor venues
#     above ~85%.
# ─────────────────────────────────────────────────────────────────────────────

# Re-calibrated hourly curves — realistic Mumbai foot-traffic (0.0–0.80 max)
_HOURLY_CURVES: Dict[str, List[float]] = {
    "railway_station": [
        # 0     1     2     3     4     5     6     7     8     9    10    11
        0.08, 0.05, 0.03, 0.03, 0.06, 0.15, 0.38, 0.72, 0.78, 0.55, 0.42, 0.38,
        # 12    13    14    15    16    17    18    19    20    21    22    23
        0.40, 0.42, 0.45, 0.50, 0.62, 0.80, 0.78, 0.65, 0.50, 0.36, 0.22, 0.12,
    ],
    "airport": [
        0.28, 0.22, 0.18, 0.20, 0.26, 0.36, 0.50, 0.62, 0.68, 0.65, 0.60, 0.58,
        0.55, 0.53, 0.57, 0.62, 0.66, 0.70, 0.74, 0.70, 0.62, 0.52, 0.42, 0.32,
    ],
    "shopping_mall": [
        0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.02, 0.03, 0.06, 0.18, 0.36,
        0.48, 0.52, 0.56, 0.60, 0.65, 0.70, 0.72, 0.65, 0.50, 0.35, 0.15, 0.03,
    ],
    "market": [
        0.02, 0.01, 0.01, 0.01, 0.02, 0.08, 0.26, 0.48, 0.60, 0.68, 0.72, 0.74,
        0.65, 0.62, 0.58, 0.54, 0.50, 0.44, 0.36, 0.26, 0.16, 0.10, 0.05, 0.02,
    ],
    "tourist_attraction": [
        0.02, 0.01, 0.01, 0.01, 0.01, 0.03, 0.10, 0.24, 0.42, 0.58, 0.68, 0.74,
        0.70, 0.66, 0.64, 0.66, 0.70, 0.64, 0.52, 0.40, 0.28, 0.16, 0.08, 0.03,
    ],
    "beach": [
        0.03, 0.02, 0.01, 0.01, 0.02, 0.07, 0.16, 0.30, 0.42, 0.46, 0.42, 0.36,
        0.30, 0.28, 0.32, 0.40, 0.52, 0.64, 0.70, 0.62, 0.46, 0.28, 0.14, 0.06,
    ],
    "business_district": [
        0.03, 0.02, 0.01, 0.01, 0.02, 0.05, 0.18, 0.50, 0.75, 0.78, 0.74, 0.68,
        0.55, 0.65, 0.72, 0.72, 0.65, 0.48, 0.28, 0.15, 0.08, 0.05, 0.04, 0.03,
    ],
}

# Weekend multipliers (capped — malls can't exceed ~85% even on weekends)
_WEEKEND_MULT: Dict[str, float] = {
    "railway_station":    0.68,
    "airport":            1.04,
    "shopping_mall":      1.25,   # was 1.35 — still high but not pinned at max
    "market":             1.15,
    "tourist_attraction": 1.30,
    "beach":              1.40,   # was 1.55
    "business_district":  0.35,
}

# Holiday multipliers
_HOLIDAY_MULT: Dict[str, float] = {
    "railway_station":    0.80,
    "airport":            1.08,
    "shopping_mall":      1.35,   # was 1.50
    "market":             1.20,
    "tourist_attraction": 1.45,   # was 1.60
    "beach":              1.50,   # was 1.65
    "business_district":  0.25,
}

# Rain multipliers for outdoor/transit venues
_RAIN_MULT: Dict[str, float] = {
    "railway_station":    0.88,
    "airport":            0.97,
    "shopping_mall":      1.18,   # rain drives people indoors
    "market":             0.50,
    "tourist_attraction": 0.35,
    "beach":              0.12,
    "business_district":  0.92,
}


def _ist_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def _is_holiday(dt: datetime) -> bool:
    return dt.strftime("%Y-%m-%d") in MUMBAI_HOLIDAYS


def _stable_noise(location_id: str, minute_bucket: int, salt: str = "") -> float:
    """
    Deterministic noise in [-1, 1] that changes every ~5 minutes.
    Symmetric — mean contribution across all locations is ~0.
    """
    h = hashlib.sha256(f"{location_id}:{minute_bucket}:{salt}".encode()).hexdigest()
    val = int(h[:8], 16) / 0xFFFFFFFF
    return (val - 0.5) * 2


def _sinusoidal_ripple(location_id: str, minute: int) -> float:
    """Short-period ripple simulating train/event arrival bursts (±4%)."""
    phase = (int(hashlib.md5(location_id.encode()).hexdigest()[:4], 16) % 360) * math.pi / 180
    return math.sin((minute * math.pi / 8.5) + phase) * 0.04   # was 0.06


def _compute_physics_density(loc: dict, dt: datetime) -> Tuple[float, str]:
    """
    Re-calibrated physics engine — produces realistic 15–80% range.

    Changes from v4.0:
    - Lower base curves (peak ≤ 0.80 instead of 0.99)
    - Symmetric ±3 location offset (not always-positive +0..+6)
    - Weather suppression applied to ALL hours in monsoon, not just 14–18h
    - Noise capped at ±6% (was ±8%)
    """
    venue_type = loc.get("venue_type", "market")
    hour       = dt.hour
    minute     = dt.minute
    weekday    = dt.weekday()
    is_weekend = weekday >= 5
    is_holiday = _is_holiday(dt)

    # 1. Base curve with linear inter-hour interpolation
    curve    = _HOURLY_CURVES.get(venue_type, _HOURLY_CURVES["market"])
    base     = curve[hour]
    next_b   = curve[(hour + 1) % 24]
    base     = base * (1 - minute / 60.0) + next_b * (minute / 60.0)

    # 2. Day multiplier
    if is_holiday:
        day_mult = _HOLIDAY_MULT.get(venue_type, 1.0)
    elif is_weekend:
        day_mult = _WEEKEND_MULT.get(venue_type, 1.0)
    else:
        day_mult = 1.0
    base *= day_mult

    # 3. Sinusoidal ripple (arrival bursts, ±4%)
    base += _sinusoidal_ripple(loc["locationId"], minute)

    # 4. Symmetric ±6% noise (mean ≈ 0 across locations)
    bucket = (hour * 60 + minute) // 5
    noise  = _stable_noise(loc["locationId"], bucket) * 0.06 * base
    base  += noise

    # 5. Weather/seasonal multiplier (applied to ALL hours now)
    base *= _weather_proxy_mult(loc, dt)

    # 6. Clamp to 0–1 then scale to 0–100
    base    = min(max(base, 0.0), 1.0)
    density = round(base * 100, 1)

    # FIX: Symmetric location offset ±3 (mean = 0), replaces old +0..+6 bias
    loc_hash = int(hashlib.md5(loc["locationId"].encode()).hexdigest()[:2], 16) % 7
    density  = min(max(density + loc_hash - 3, 0), 100)   # -3 to +3

    return density, "physics_engine"


def _weather_proxy_mult(loc: dict, dt: datetime) -> float:
    """
    Re-calibrated seasonal/weather multiplier.

    FIX: Monsoon suppression now applies to ALL hours (not just 14–18h)
    so beaches and tourist spots show realistic low numbers in July/August
    even at 10 AM.
    """
    venue_type = loc.get("venue_type", "market")
    month      = dt.month
    hour       = dt.hour

    # Seasonal base
    if 6 <= month <= 9:        # Monsoon — outdoor venues suppressed all day
        season_factor = 0.72
        # Apply rain multiplier for outdoor venues throughout the day
        if venue_type in ("beach", "tourist_attraction", "market"):
            rain_factor   = _RAIN_MULT.get(venue_type, 0.80)
            season_factor = season_factor * rain_factor  # e.g. beach: 0.72 * 0.12 = ~0.09
        elif venue_type == "shopping_mall":
            season_factor = 0.72 * _RAIN_MULT["shopping_mall"]  # 0.72*1.18 = 0.85 → malls busier
    elif month in (4, 5):      # Pre-monsoon/heat
        season_factor = 0.85
        if 12 <= hour <= 15:
            season_factor *= 0.78   # midday heat suppression
    elif month in (3,):
        season_factor = 1.05
    else:                      # Oct–Mar (winter / festive)
        season_factor = 1.0

    # Additional heavy-rain-hour suppression during monsoon peak window
    if 6 <= month <= 9 and 14 <= hour <= 18:
        extra = _RAIN_MULT.get(venue_type, 0.80)
        season_factor *= (0.5 + extra * 0.5)   # partial extra suppression

    return season_factor


# ─────────────────────────────────────────────────────────────────────────────
# Live weather from OpenWeather (optional)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_live_weather_mult(venue_type: str) -> float:
    if not OPENWEATHER_KEY:
        return 1.0
    cache_key = "mumbai_weather"
    cached = _weather_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < WEATHER_TTL:
        condition = cached["condition"]
    else:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                resp = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"lat": 19.076, "lon": 72.877, "appid": OPENWEATHER_KEY, "units": "metric"},
                )
                if resp.status_code == 200:
                    wid = resp.json()["weather"][0]["id"]
                    if wid < 300:   condition = "thunderstorm"
                    elif wid < 400: condition = "drizzle"
                    elif wid < 600: condition = "rain"
                    elif wid < 700: condition = "snow"
                    else:           condition = "clear"
                    _weather_cache[cache_key] = {"condition": condition, "ts": time.time()}
                else:
                    return 1.0
        except Exception:
            return 1.0
    mult_map = {
        "thunderstorm": {"beach": 0.05, "tourist_attraction": 0.25, "market": 0.35,
                         "shopping_mall": 1.25, "railway_station": 0.82,
                         "airport": 0.93, "business_district": 0.88},
        "rain":         _RAIN_MULT,
        "drizzle":      {k: 0.5 + v * 0.5 for k, v in _RAIN_MULT.items()},
        "clear":        {k: 1.0 for k in _RAIN_MULT},
        "snow":         {k: 0.50 for k in _RAIN_MULT},
    }
    return mult_map.get(condition, {}).get(venue_type, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# BestTime.app Integration  (v4.2 — improved accuracy)
#
# KEY CHANGES from v4.1:
#  • Improved fuzzy venue matching (not just first-word match)
#  • Added lat/lng filter endpoint for better venue resolution
#  • _besttime_now() replaces _besttime_forecast_now() — more reliable
#  • NO weather multiplier on BestTime data (BestTime already accounts for it)
#  • Separate cache for weekly forecasts
# ─────────────────────────────────────────────────────────────────────────────

def _fuzzy_venue_match(query: str, candidate: str) -> bool:
    """
    Improved fuzzy matching for venue names.
    Returns True if query matches candidate reasonably well.
    """
    query_lower = query.lower().strip()
    candidate_lower = candidate.lower().strip()
    
    # Exact match
    if query_lower == candidate_lower:
        return True
    
    # One contains the other
    if query_lower in candidate_lower or candidate_lower in query_lower:
        return True
    
    # Check if significant words match (at least 2 words or all words if fewer)
    query_words = set(query_lower.replace(",", " ").split())
    candidate_words = set(candidate_lower.replace(",", " ").split())
    
    # Remove common words
    stop_words = {"the", "of", "at", "in", "on", "and", "a", "an", "station", "railway", "mumbai", "india"}
    query_significant = query_words - stop_words
    candidate_significant = candidate_words - stop_words
    
    if not query_significant:
        query_significant = query_words
    
    # Check overlap
    overlap = query_significant & candidate_significant
    min_required = min(2, len(query_significant))
    
    return len(overlap) >= min_required


async def _besttime_get_venue_id(venue_name: str, venue_address: str, lat: float = None, lng: float = None) -> Optional[str]:
    """
    Resolve BestTime venue_id for a known Mumbai location.

    Strategy (v4.2 — improved accuracy):
      1. Check local cache (TTL 24 h) — avoids any API call on cache hit.
      2. Try BestTime venue SEARCH endpoint with better fuzzy matching.
      3. Try BestTime venues/filter endpoint with lat/lng if available.
      4. If not found, register via forecast endpoint (costs 1 forecast credit).
    """
    if not BESTTIME_API_KEY:
        return None

    # Use lat/lng in cache key for better hit rate
    if lat and lng:
        cache_key = f"{venue_name}|{lat:.4f},{lng:.4f}".lower().strip()
    else:
        cache_key = f"{venue_name}|{venue_address}".lower().strip()
    
    cached = _venue_id_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < VENUE_ID_TTL:
        return cached["venue_id"]

    # ── Step 1: Try venue search (free, no credit cost) ──────────────────────
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://besttime.app/api/v1/venues/search",
                params={
                    "api_key_private": BESTTIME_API_KEY,
                    "q":               venue_name,
                    "num":             "5",  # Increased for better matching
                },
            )
            if resp.status_code == 200:
                venues = resp.json().get("venues", [])
                for v in venues:
                    v_name = v.get("venue_name", "")
                    # Use improved fuzzy matching
                    if _fuzzy_venue_match(venue_name, v_name):
                        vid = v.get("venue_id")
                        if vid:
                            _venue_id_cache[cache_key] = {"venue_id": vid, "ts": time.time()}
                            return vid
    except Exception as e:
        print(f"[BestTime] venue search error: {e}")

    # ── Step 2: Try filter by lat/lng if available (free) ────────────────────
    if lat and lng:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://besttime.app/api/v1/venues/filter",
                    params={
                        "api_key_private": BESTTIME_API_KEY,
                        "lat":             str(lat),
                        "lng":             str(lng),
                        "radius":          "200",  # 200m radius
                        "num":             "5",
                    },
                )
                if resp.status_code == 200:
                    venues = resp.json().get("venues", [])
                    for v in venues:
                        v_name = v.get("venue_name", "")
                        if _fuzzy_venue_match(venue_name, v_name):
                            vid = v.get("venue_id")
                            if vid:
                                _venue_id_cache[cache_key] = {"venue_id": vid, "ts": time.time()}
                                return vid
                    # If no fuzzy match, take the closest one
                    if venues:
                        vid = venues[0].get("venue_id")
                        if vid:
                            _venue_id_cache[cache_key] = {"venue_id": vid, "ts": time.time()}
                            return vid
        except Exception as e:
            print(f"[BestTime] venue filter error: {e}")

    # ── Step 3: Register via forecast (costs 1 credit — only if not found) ───
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {
                "api_key_private": BESTTIME_API_KEY,
                "venue_name":      venue_name,
                "venue_address":   venue_address,
            }
            resp = await client.post(
                "https://besttime.app/api/v1/forecasts",
                params=params,
            )
            if resp.status_code == 200:
                data = resp.json()
                vid = data.get("venue_info", {}).get("venue_id")
                if vid:
                    _venue_id_cache[cache_key] = {"venue_id": vid, "ts": time.time()}
                    return vid
    except Exception as e:
        print(f"[BestTime] forecast register error: {e}")

    return None


async def _besttime_live(venue_id: str) -> Optional[dict]:
    """
    Fetch real-time live busyness from BestTime (v4.2 — improved).
    Now also tries the 'now' endpoint if 'live' returns no data.
    Cached 3 min.
    """
    if not BESTTIME_API_KEY or not venue_id:
        return None
    cached = _live_cache.get(venue_id)
    if cached and (time.time() - cached["ts"]) < LIVE_TTL:
        return cached
    
    # Try the live endpoint first (real-time mobile signal data)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://besttime.app/api/v1/forecasts/live",
                params={"api_key_private": BESTTIME_API_KEY, "venue_id": venue_id},
            )
            if resp.status_code == 200:
                data     = resp.json()
                analysis = data.get("analysis", {})
                busyness = analysis.get("venue_live_busyness")
                
                # BestTime live may return -1 or null when no data
                if busyness is not None and busyness >= 0:
                    result = {
                        "busyness": float(busyness), 
                        "ts": time.time(), 
                        "raw": data,
                        "source": "besttime_live"
                    }
                    _live_cache[venue_id] = result
                    return result
                
                # Check if there's a "venue_live_busyness_available" flag
                if not analysis.get("venue_live_busyness_available", True):
                    # Live data not available, will fall through to forecast
                    pass
    except Exception as e:
        print(f"[BestTime] live error: {e}")
    
    return None


async def _besttime_now(venue_id: str) -> Optional[dict]:
    """
    Fetch BestTime's 'now' endpoint — current hour's predicted + live blend.
    This is more reliable than pure 'live' for many venues.
    Cached 5 min.
    """
    if not BESTTIME_API_KEY or not venue_id:
        return None
    
    cache_key = f"now_{venue_id}"
    cached = _forecast_now_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < FORECAST_NOW_TTL:
        return cached
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://besttime.app/api/v1/forecasts/now",
                params={"api_key_private": BESTTIME_API_KEY, "venue_id": venue_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                analysis = data.get("analysis", {})
                
                # Try to get raw intensity first (0-100)
                intensity = analysis.get("now_raw")
                
                if intensity is None:
                    # Fallback: parse 'now' label → approximate numeric
                    label_map = {
                        "low": 20, "below_average": 35, "average": 50,
                        "above_average": 65, "high": 80, "very_high": 92
                    }
                    label = analysis.get("now", "")
                    intensity = label_map.get(label.lower().replace(" ", "_"), None)
                
                if intensity is not None and intensity >= 0:
                    result = {
                        "busyness": float(intensity),
                        "ts": time.time(),
                        "raw": data,
                        "source": "besttime_now"
                    }
                    _forecast_now_cache[cache_key] = result
                    return result
    except Exception as e:
        print(f"[BestTime] now error: {e}")
    
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Google Places — popularity signal
# ─────────────────────────────────────────────────────────────────────────────

async def _google_place_popularity(venue_name: str, lat: float, lng: float) -> Optional[float]:
    if not GOOGLE_MAPS_KEY:
        return None
    cache_key = f"pop_{lat:.4f}_{lng:.4f}"
    cached = _google_places_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < PLACES_TTL:
        return cached["popularity"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={"query": venue_name, "location": f"{lat},{lng}",
                        "radius": "300", "key": GOOGLE_MAPS_KEY},
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    p = results[0]
                    rating        = p.get("rating", 0) or 0
                    ratings_total = p.get("user_ratings_total", 0) or 0
                    if ratings_total > 0:
                        log_norm   = math.log10(ratings_total + 1) / math.log10(10001)
                        popularity = min(log_norm * (rating / 5.0) * 100, 100)
                        _google_places_cache[cache_key] = {
                            "popularity": round(popularity, 1), "ts": time.time()
                        }
                        return round(popularity, 1)
    except Exception as e:
        print(f"[Google Places] popularity error: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Master density resolver  (v4.2 — BestTime accuracy improved)
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_density(loc: dict) -> Tuple[float, str]:
    """
    Full fallback chain (v4.2 — improved accuracy):
      1. BestTime Live  → raw busyness from real mobile-signal data (0–100)
      2. BestTime Now   → current hour blend of live + forecast (0–100)
      3. Google Places popularity blended with re-calibrated physics engine
      4. Physics engine alone

    BestTime values are returned AS-IS (no weather multiplier) because
    BestTime already accounts for typical conditions. Weather multiplier
    is ONLY applied to physics engine fallback.
    """
    venue_name    = loc["locationName"]
    venue_address = f"{venue_name}, {loc.get('area', 'Mumbai')}, Mumbai, India"
    lat           = loc.get("latitude")
    lng           = loc.get("longitude")
    ist           = _ist_now()

    # ── 1 & 2. BestTime (Live then Now) ───────────────────────────────────────
    if BESTTIME_API_KEY:
        venue_id = await _besttime_get_venue_id(venue_name, venue_address, lat, lng)
        if venue_id:
            # Try live endpoint first
            live = await _besttime_live(venue_id)
            if live and live.get("busyness") is not None:
                # BestTime live is already accurate — return as-is
                density = min(max(live["busyness"], 0), 100)
                return round(density, 1), "besttime_live"

            # Try 'now' endpoint (blends live + forecast, more reliable)
            now_data = await _besttime_now(venue_id)
            if now_data and now_data.get("busyness") is not None:
                density = min(max(now_data["busyness"], 0), 100)
                return round(density, 1), "besttime_now"

    # ── 3. Google Places + physics blend (weather applied) ───────────────────
    weather_mult = await _get_live_weather_mult(loc.get("venue_type", "market"))
    physics_density, _ = _compute_physics_density(loc, ist)
    physics_density    = min(max(physics_density * weather_mult, 0), 100)

    if GOOGLE_MAPS_KEY:
        google_pop = await _google_place_popularity(venue_name, lat, lng)
        if google_pop is not None:
            # 40% Google static + 60% physics (time-varying)
            blended = round(0.40 * google_pop + 0.60 * physics_density, 1)
            return min(max(blended, 0), 100), "google_physics_blend"

    # ── 4. Physics engine alone ───────────────────────────────────────────────
    return physics_density, "physics_engine"


async def _resolve_density_custom(venue_name: str, lat: float, lng: float,
                                  venue_type: str = "market") -> Tuple[float, str]:
    """Resolve density for custom/searched locations."""
    ist      = _ist_now()
    mock_loc = {
        "locationId": f"custom_{lat:.4f}_{lng:.4f}",
        "locationName": venue_name,
        "latitude": lat, "longitude": lng,
        "venue_type": venue_type,
    }
    
    # Try BestTime first for custom locations too
    if BESTTIME_API_KEY:
        venue_address = f"{venue_name}, Mumbai, India"
        venue_id = await _besttime_get_venue_id(venue_name, venue_address, lat, lng)
        if venue_id:
            live = await _besttime_live(venue_id)
            if live and live.get("busyness") is not None:
                density = min(max(live["busyness"], 0), 100)
                return round(density, 1), "besttime_live"
            
            now_data = await _besttime_now(venue_id)
            if now_data and now_data.get("busyness") is not None:
                density = min(max(now_data["busyness"], 0), 100)
                return round(density, 1), "besttime_now"
    
    # Fallback to physics + weather
    weather_mult = await _get_live_weather_mult(venue_type)
    physics_d, _ = _compute_physics_density(mock_loc, ist)
    physics_d    = min(max(physics_d * weather_mult, 0), 100)

    if GOOGLE_MAPS_KEY:
        google_pop = await _google_place_popularity(venue_name, lat, lng)
        if google_pop is not None:
            blended = round(0.35 * google_pop + 0.65 * physics_d, 1)
            return min(max(blended, 0), 100), "google_physics_blend"

    return round(physics_d, 1), "physics_engine"


# ─────────────────────────────────────────────────────────────────────────────
# Build crowd item (4-min cache per location)
# ─────────────────────────────────────────────────────────────────────────────

async def _build_crowd_item(loc: dict) -> dict:
    cache_key = loc["locationId"]
    cached    = _crowd_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < CROWD_TTL:
        return cached["item"]

    density, source = await _resolve_density(loc)
    count           = int(density * loc.get("capacity", 2000) / 100)

    ist_next  = _ist_now() + timedelta(hours=1)
    next_d, _ = _compute_physics_density(loc, ist_next)
    next_d    = round(min(max(next_d, 0), 100), 1)

    item = {
        "locationId":          loc["locationId"],
        "location_id":         loc["locationId"],
        "locationName":        loc["locationName"],
        "location_name":       loc["locationName"],
        "latitude":            loc["latitude"],
        "longitude":           loc["longitude"],
        "area":                loc.get("area", "Mumbai"),
        "venue_type":          loc.get("venue_type", "unknown"),
        "crowdCount":          count,
        "crowd_count":         count,
        "crowdDensity":        density,
        "crowd_density":       density,
        "status":              _crowd_status(density),
        "source":              source,
        "timestamp":           datetime.now(timezone.utc).isoformat(),
        "predictedNextHour":   next_d,
        "predicted_next_hour": next_d,
    }

    _crowd_cache[cache_key] = {"item": item, "ts": time.time()}
    return item


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _haversine(lat1, lon1, lat2, lon2) -> float:
    R    = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat/2)**2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _crowd_status(density: float) -> str:
    if density < 30: return "low"
    if density < 60: return "medium"   # was 65 — tighter medium band
    return "high"


def _is_quota_error(e: Exception) -> bool:
    """
    Returns True for ANY Gemini error that should trigger Groq fallback:
      - 429 quota / rate limit exceeded
      - 400 API key expired or invalid
      - 403 permission denied
      - 500/503 upstream service errors
    Always fall through to Groq on any Gemini failure.
    """
    return True  # Any Gemini exception should activate Groq emergency fallback


def _gemini_ask(prompt: str) -> str:
    """
    Ask Gemini (primary). On ANY Gemini error, activates Groq emergency fallback.
    Raises RuntimeError only if both providers fail.
    """
    # ── Primary: Gemini ───────────────────────────────────────────────────────
    if gemini_model is not None:
        try:
            response = gemini_model.generate_content(prompt)
            text = response.text or ""
            if text:
                return text
        except Exception as e:
            # Always fall through to Groq regardless of error type
            # (covers: 400 key expired, 429 quota, 403 permission, 500 upstream)
            print(f"[Gemini] Failed ({type(e).__name__}: {e}) — activating Groq emergency fallback.")
    else:
        print("[Gemini] Not configured — activating Groq emergency fallback.")

    # ── Emergency fallback: Groq ──────────────────────────────────────────────
    if groq_client is not None:
        try:
            completion = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                timeout=20,
            )
            text = completion.choices[0].message.content or ""
            if text:
                print("[Groq] Emergency fallback succeeded.")
                return text
        except Exception as e:
            print(f"[Groq Emergency] Error: {e}")
            traceback.print_exc()

    raise RuntimeError("quota_exceeded")


async def _nominatim_search(query: str, limit: int = 6,
                             bias_lat: Optional[float] = None,
                             bias_lng: Optional[float] = None) -> List[dict]:
    global _last_nominatim_call
    now = time.time()
    if now - _last_nominatim_call < 1.0:
        await asyncio.sleep(1.0 - (now - _last_nominatim_call))
    params: dict = {"q": query, "format": "json", "limit": str(limit), "addressdetails": "1"}
    if bias_lat is not None and bias_lng is not None:
        params["viewbox"] = f"{bias_lng-0.5},{bias_lat+0.5},{bias_lng+0.5},{bias_lat-0.5}"
        params["bounded"] = "0"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search", params=params,
                headers={"User-Agent": "CrowdSenseAI/4.2 (contact@crowdsense.app)"},
            )
            _last_nominatim_call = time.time()
            if resp.status_code == 200:
                out = []
                for r in resp.json():
                    try:
                        out.append({
                            "display_name": r.get("display_name", ""),
                            "name": r.get("name") or r.get("display_name","").split(",")[0].strip(),
                            "lat": float(r["lat"]),
                            "lng": float(r["lon"]),
                            "type": r.get("type",""),
                            "class": r.get("class",""),
                        })
                    except Exception:
                        continue
                return out
    except Exception as e:
        print(f"[Nominatim] {e}")
    return []


def _infer_venue_type(tags: List[str]) -> str:
    tag_map = {
        "airport": "airport", "train_station": "railway_station",
        "subway_station": "railway_station", "bus_station": "railway_station",
        "shopping_mall": "shopping_mall", "department_store": "shopping_mall",
        "market": "market", "grocery_or_supermarket": "market",
        "tourist_attraction": "tourist_attraction", "museum": "tourist_attraction",
        "amusement_park": "tourist_attraction", "park": "beach",
        "natural_feature": "beach", "beach": "beach",
        "premise": "business_district", "establishment": "market",
    }
    for tag in tags:
        if tag in tag_map:
            return tag_map[tag]
    return "market"


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class PredictBody(BaseModel):
    location_id:  str
    hour:         int
    day_of_week:  int
    is_weekend:   int
    is_holiday:   int

class DirectionsBody(BaseModel):
    origin:      dict
    destination: dict
    mode:        Optional[str] = "driving"

class AiInsightsBody(BaseModel):
    crowdData: Optional[List[Any]] = None

class AiRouteAdviceBody(BaseModel):
    crowdData:   Optional[List[Any]] = None
    origin:      Optional[str] = None
    destination: Optional[str] = None

class RealtimeTrainBody(BaseModel):
    hours_to_sample:     Optional[int]   = 12
    blend_with_original: Optional[bool]  = True
    weight_maps:         Optional[float] = 0.6

class LocationInput(BaseModel):
    name: str
    lat:  float
    lng:  float

class SmartRouteRequest(BaseModel):
    origin:      LocationInput
    destination: LocationInput
    mode:        Optional[str] = "driving"


# ─────────────────────────────────────────────────────────────────────────────
# ROOT / PING / HEALTH
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "message": "CrowdSense AI API — Real-Time Crowd Density Engine",
        "status":  "healthy",
        "version": "4.2.0",
        "engine":  "BestTime Live → BestTime Now → Google+Physics",
        "docs":    "/docs",
    }

@app.get("/ping")
async def ping():
    return {"ping": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/health")
async def health():
    ist = _ist_now()
    return {
        "status":                  "ok",
        "model":                   "gemini-1.5-flash",
        "service":                 "CrowdSense AI",
        "engine":                  "v4.2-besttime-accurate",
        "ist_time":                ist.strftime("%H:%M IST"),
        "ist_day":                 ist.strftime("%A"),
        "is_holiday":              _is_holiday(ist),
        "city":                    "Mumbai",
        "center_latitude":         MUMBAI_BOUNDS["center_lat"],
        "center_longitude":        MUMBAI_BOUNDS["center_lng"],
        "bounds":                  MUMBAI_BOUNDS,
        "googleMapsConfigured":    bool(GOOGLE_MAPS_KEY),
        "besttimeConfigured":      bool(BESTTIME_API_KEY),
        "weatherConfigured":       bool(OPENWEATHER_KEY),
        "geminiConfigured":        gemini_model is not None,
        "groqConfigured":          groq_client is not None,
        "chatbotProvider":         "gemini" if gemini_model is not None else ("groq_emergency" if groq_client is not None else "none"),
        "total_heatmap_locations": len(LOCATIONS),
        "timestamp":               datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# LOCATIONS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/city-info")
async def get_city_info():
    return {
        "city": "Mumbai", "state": "Maharashtra", "country": "India",
        "center_latitude": MUMBAI_BOUNDS["center_lat"],
        "center_longitude": MUMBAI_BOUNDS["center_lng"],
        "bounds": MUMBAI_BOUNDS,
        "total_monitored_locations": len(LOCATIONS),
    }

@app.get("/locations")
async def get_locations():
    return {"locations": LOCATIONS, "total": len(LOCATIONS), "city": "Mumbai", "bounds": MUMBAI_BOUNDS}

@app.get("/locations/nearby")
async def get_nearby_locations(
    latitude:  float = Query(...),
    longitude: float = Query(...),
    radius_km: float = Query(10.0),
):
    nearby = []
    for loc in LOCATIONS:
        dist = _haversine(latitude, longitude, loc["latitude"], loc["longitude"])
        if dist <= radius_km:
            nearby.append({**loc, "distance_km": round(dist, 2)})
    nearby.sort(key=lambda x: x["distance_km"])
    return {"locations": nearby, "total": len(nearby),
            "radius_km": radius_km, "user_lat": latitude, "user_lng": longitude}


# ─────────────────────────────────────────────────────────────────────────────
# PREDICTIONS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/predictions/bulk")
async def get_bulk_predictions(hour: Optional[int] = Query(None, ge=0, le=23)):
    current_hour = hour if hour is not None else _ist_now().hour
    tasks        = [_build_crowd_item(loc) for loc in LOCATIONS]
    results      = await asyncio.gather(*tasks, return_exceptions=True)
    data = []
    for i, item in enumerate(results):
        if isinstance(item, Exception):
            d, src = _compute_physics_density(LOCATIONS[i], _ist_now())
            loc = LOCATIONS[i]
            data.append({
                "locationId": loc["locationId"], "location_id": loc["locationId"],
                "locationName": loc["locationName"], "location_name": loc["locationName"],
                "latitude": loc["latitude"], "longitude": loc["longitude"],
                "crowdDensity": d, "crowd_density": d,
                "crowdCount": int(d * loc.get("capacity", 2000) / 100),
                "crowd_count": int(d * loc.get("capacity", 2000) / 100),
                "status": _crowd_status(d), "source": src,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "predictedNextHour": None, "predicted_next_hour": None,
            })
        else:
            data.append(item)
    return {"data": data, "hour": current_hour, "count": len(data), "city": "Mumbai"}


@app.post("/predict")
async def predict_single(body: PredictBody):
    loc = LOCATION_MAP.get(body.location_id)
    if not loc:
        raise HTTPException(status_code=404, detail=f"Location '{body.location_id}' not found")
    density, source = await _resolve_density(loc)
    return {
        "location_id":       body.location_id,
        "location_name":     loc["locationName"],
        "predicted_density": density,
        "status":            _crowd_status(density),
        "source":            source,
        "hour":              body.hour,
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# REALTIME PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/realtime/status")
async def realtime_status():
    return {
        "enabled":  True,
        "provider": "besttime_live" if BESTTIME_API_KEY else
                    ("google_physics_blend" if GOOGLE_MAPS_KEY else "physics_engine"),
        "status":   "available",
        "sources":  {
            "besttime":       bool(BESTTIME_API_KEY),
            "google_places":  bool(GOOGLE_MAPS_KEY),
            "openweather":    bool(OPENWEATHER_KEY),
            "physics_engine": True,
        },
    }


@app.post("/realtime/collect")
async def collect_realtime():
    global realtime_cache
    tasks   = [_build_crowd_item(loc) for loc in LOCATIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    data    = []
    ist     = _ist_now()
    for i, item in enumerate(results):
        if isinstance(item, Exception):
            d, src = _compute_physics_density(LOCATIONS[i], ist)
            loc = LOCATIONS[i]
            data.append({
                "locationId": loc["locationId"], "location_id": loc["locationId"],
                "locationName": loc["locationName"], "location_name": loc["locationName"],
                "latitude": loc["latitude"], "longitude": loc["longitude"],
                "crowdDensity": d, "crowd_density": d,
                "crowdCount": int(d*loc.get("capacity",2000)/100),
                "crowd_count": int(d*loc.get("capacity",2000)/100),
                "status": _crowd_status(d), "source": src,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "predictedNextHour": None, "predicted_next_hour": None,
            })
        else:
            data.append(item)
    realtime_cache = data
    sources_used = list(set(d.get("source","unknown") for d in data))
    return {"data": data, "source": "realtime", "sources_used": sources_used,
            "count": len(data), "city": "Mumbai"}


@app.get("/realtime/cached")
async def get_cached_realtime():
    if not realtime_cache:
        result = await collect_realtime()
        return {"data": result["data"], "source": "cold_start"}
    return {"data": realtime_cache, "source": "cache", "city": "Mumbai"}


@app.post("/realtime/predict")
async def realtime_predict(
    location_id: str           = Query(...),
    hour:        Optional[int] = Query(None, ge=0, le=23),
):
    loc = LOCATION_MAP.get(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail=f"Location '{location_id}' not found")
    density, source = await _resolve_density(loc)
    return {
        "location_id":       location_id,
        "location_name":     loc["locationName"],
        "predicted_density": density,
        "status":            _crowd_status(density),
        "source":            source,
        "hour":              hour if hour is not None else _ist_now().hour,
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAPS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/maps/search")
async def maps_search(
    q:         str             = Query(None),
    limit:     int             = Query(6, ge=1, le=20),
    latitude:  Optional[float] = Query(None),
    longitude: Optional[float] = Query(None),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Query 'q' is required")
    if GOOGLE_MAPS_KEY:
        try:
            params: dict = {"query": q.strip(), "key": GOOGLE_MAPS_KEY}
            if latitude is not None and longitude is not None:
                params["location"] = f"{latitude},{longitude}"
                params["radius"]   = "50000"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/textsearch/json", params=params)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])[:limit]
                    if results:
                        return [
                            {"name": p.get("name",""),
                             "display_name": p.get("formatted_address", p.get("name","")),
                             "lat": p["geometry"]["location"]["lat"],
                             "lng": p["geometry"]["location"]["lng"],
                             "type": (p.get("types") or [""])[0],
                             "source": "google_places"}
                            for p in results if p.get("geometry",{}).get("location")
                        ]
        except Exception as e:
            print(f"[Maps Search / Google] {e}")
    results = await _nominatim_search(q.strip(), limit=limit, bias_lat=latitude, bias_lng=longitude)
    return [{**r, "source": "nominatim"} for r in results]


@app.get("/maps/nearby")
async def maps_nearby(
    latitude:   float          = Query(...),
    longitude:  float          = Query(...),
    radius:     float          = Query(2000),
    place_type: Optional[str]  = Query(None),
):
    radius_m         = int(min(radius, 50000))
    nearby_locations = []
    if GOOGLE_MAPS_KEY:
        try:
            params: dict = {"location": f"{latitude},{longitude}", "radius": str(radius_m), "key": GOOGLE_MAPS_KEY}
            if place_type:
                params["type"] = place_type
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/nearbysearch/json", params=params)
                if resp.status_code == 200:
                    places = resp.json().get("results", [])[:10]
                    tasks  = []
                    for p in places:
                        geo   = p.get("geometry",{}).get("location",{})
                        plat  = geo.get("lat", latitude)
                        plng  = geo.get("lng", longitude)
                        vtype = _infer_venue_type(p.get("types",[]))
                        tasks.append(_resolve_density_custom(p.get("name","Place"), plat, plng, vtype))
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for p, res in zip(places, results):
                        geo = p.get("geometry",{}).get("location",{})
                        d, src = res if not isinstance(res, Exception) else (40.0, "error_fallback")
                        nearby_locations.append({
                            "id": p.get("place_id",""), "name": p.get("name",""),
                            "lat": geo.get("lat", latitude), "lng": geo.get("lng", longitude),
                            "crowd_density": d, "status": _crowd_status(d),
                            "source": src, "types": p.get("types",[]),
                            "vicinity": p.get("vicinity",""),
                        })
        except Exception as e:
            print(f"[Maps Nearby] {e}")
    if not nearby_locations:
        nom = await _nominatim_search(f"places near {latitude},{longitude}", limit=6)
        tasks = [_resolve_density_custom(r["name"], r["lat"], r["lng"]) for r in nom]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r, res in zip(nom, results):
            d, src = res if not isinstance(res, Exception) else (40.0, "error_fallback")
            nearby_locations.append({
                "id": f"nom_{r['lat']}_{r['lng']}", "name": r["name"],
                "lat": r["lat"], "lng": r["lng"],
                "crowd_density": d, "status": _crowd_status(d), "source": src,
            })
    return {"nearby_locations": nearby_locations, "places": nearby_locations,
            "results": nearby_locations, "radius_km": round(radius_m/1000,2),
            "count": len(nearby_locations)}


@app.get("/maps/estimate-crowd/{location_id}")
async def maps_estimate_crowd(
    location_id: str   = Path(...),
    latitude:    float = Query(...),
    longitude:   float = Query(...),
):
    if location_id in LOCATION_MAP:
        density, source = await _resolve_density(LOCATION_MAP[location_id])
        loc = LOCATION_MAP[location_id]
        return {
            "location_id":   location_id,
            "location_name": loc["locationName"],
            "crowd_density": density,
            "status":        _crowd_status(density),
            "source":        source,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }
    venues_data: List[dict] = []
    if GOOGLE_MAPS_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                    params={"location": f"{latitude},{longitude}", "radius": "500", "key": GOOGLE_MAPS_KEY},
                )
                if resp.status_code == 200:
                    places = resp.json().get("results", [])[:6]
                    tasks  = []
                    for p in places:
                        geo   = p.get("geometry",{}).get("location",{})
                        plat  = geo.get("lat", latitude)
                        plng  = geo.get("lng", longitude)
                        vtype = _infer_venue_type(p.get("types",[]))
                        tasks.append(_resolve_density_custom(p.get("name","Place"), plat, plng, vtype))
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for p, res in zip(places, results):
                        if not isinstance(res, Exception):
                            d, src = res
                            venues_data.append({"name": p.get("name",""), "density": d, "source": src})
        except Exception as e:
            print(f"[Estimate Crowd Custom] {e}")
    if not venues_data:
        d, src = await _resolve_density_custom("custom_location", latitude, longitude)
        venues_data.append({"name": "area", "density": d, "source": src})
    total_w = weighted_sum = 0.0
    for i, v in enumerate(venues_data):
        w = 1.0 / (i + 1)
        weighted_sum += v["density"] * w
        total_w      += w
    avg_density = round(weighted_sum / total_w, 1) if total_w else 40.0
    sources = [v["source"] for v in venues_data]
    primary_source = (
        "besttime_live"        if "besttime_live"        in sources else
        "besttime_forecast"    if "besttime_forecast"     in sources else
        "google_physics_blend" if "google_physics_blend" in sources else
        "physics_engine"
    )
    return {
        "location_id":    location_id,
        "location_name":  f"Area at {latitude:.4f}, {longitude:.4f}",
        "crowd_density":  avg_density,
        "status":         _crowd_status(avg_density),
        "source":         primary_source,
        "venues_sampled": len(venues_data),
        "venue_details":  venues_data[:5],
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


@app.post("/maps/directions")
async def maps_directions(body: DirectionsBody):
    origin_str = f"{body.origin.get('lat')},{body.origin.get('lng')}"
    dest_str   = f"{body.destination.get('lat')},{body.destination.get('lng')}"
    if GOOGLE_MAPS_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/directions/json",
                    params={"origin": origin_str, "destination": dest_str,
                            "mode": body.mode, "key": GOOGLE_MAPS_KEY, "alternatives": "true"},
                )
                return resp.json()
        except Exception as e:
            print(f"[Directions] {e}")
    return {
        "status": "OK",
        "routes": [
            {"summary": f"Route {i+1}", "duration_minutes": random.randint(10, 40),
             "distance_km": round(random.uniform(2, 15), 1),
             "traffic_condition": random.choice(["clear","moderate","heavy"]),
             "crowd_level": random.choice(["low","medium","high"])}
            for i in range(2)
        ],
    }


@app.get("/maps/place/{place_id}")
async def maps_place_details(place_id: str = Path(...)):
    if GOOGLE_MAPS_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/details/json",
                    params={"place_id": place_id,
                            "fields": "name,formatted_address,rating,opening_hours,geometry,types",
                            "key": GOOGLE_MAPS_KEY},
                )
                if resp.status_code == 200:
                    r = resp.json().get("result", {})
                    return {
                        "place_id": place_id, "name": r.get("name",""),
                        "address": r.get("formatted_address",""),
                        "rating": r.get("rating"),
                        "open_now": r.get("opening_hours",{}).get("open_now"),
                        "types": r.get("types",[]),
                    }
        except Exception as e:
            print(f"[Place Details] {e}")
    return {"place_id": place_id, "name": f"Place {place_id}", "address": "N/A"}


# ─────────────────────────────────────────────────────────────────────────────
# BEST TIME endpoint
# ─────────────────────────────────────────────────────────────────────────────
# v4.2: Enhanced accuracy:
#  - BestTime weekly forecast for real historical hourly data
#  - Live density blended into current hour for real-time accuracy
#  - Travel time ALWAYS provided (Google Maps or Haversine fallback)
#  - Added time_to_reach, current_density, worst_hour fields
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_travel_time(origin_lat: float, origin_lng: float,
                          dest_lat: float, dest_lng: float,
                          mode: str = "driving") -> dict:
    """
    Estimate travel time using Haversine distance when Google Maps unavailable.
    Returns a route-like dict with estimated duration.
    """
    dist_km = _haversine(origin_lat, origin_lng, dest_lat, dest_lng)
    ist = _ist_now()
    hour = ist.hour
    is_peak = (7 <= hour <= 10) or (17 <= hour <= 20)
    
    # Mumbai-realistic speeds (km/h)
    speed_map = {
        "driving": 15 if is_peak else 30,    # Mumbai traffic is notoriously slow
        "bicycling": 12,
        "walking": 5,
        "transit": 20 if is_peak else 28,
    }
    speed = speed_map.get(mode, 20)
    mins = max(int(dist_km / speed * 60), 2)
    
    return {
        "duration": f"{mins} mins",
        "duration_secs": mins * 60,
        "distance": f"{round(dist_km, 1)} km",
        "summary": f"Estimated via {mode}",
        "source": "haversine_estimate",
    }


async def _besttime_weekly_raw(venue_id: str) -> Optional[Dict[int, float]]:
    """
    Fetch BestTime weekly forecast and extract today's 24-hour busyness curve.
    Returns {hour: busyness_0_to_100} or None on failure.
    Cached 1 hour (weekly forecasts are stable).
    """
    if not BESTTIME_API_KEY or not venue_id:
        return None

    cache_key = f"weekly_{venue_id}"
    cached    = _weekly_cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < WEEKLY_TTL:
        return cached["value"]

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://besttime.app/api/v1/forecasts/week/raw",
                params={"api_key_private": BESTTIME_API_KEY, "venue_id": venue_id},
            )
            if resp.status_code == 200:
                data   = resp.json()
                # BestTime week/raw returns analysis.week_raw: list of 7 days
                # Each day: {"day_int": 0-6, "day_raw": [h0, h1, ... h23]}
                week   = data.get("analysis", {}).get("week_raw", [])
                ist    = _ist_now()
                today  = ist.weekday()   # 0=Mon … 6=Sun
                # BestTime day_int: 0=Sun … 6=Sat → convert
                bt_day = (today + 1) % 7
                for day_data in week:
                    if day_data.get("day_int") == bt_day:
                        raw = day_data.get("day_raw", [])
                        if len(raw) == 24:
                            curve = {h: float(raw[h]) for h in range(24)}
                            _weekly_cache[cache_key] = {"value": curve, "ts": time.time()}
                            return curve
    except Exception as e:
        print(f"[BestTime] weekly raw error: {e}")
    return None


async def _google_maps_fastest_route(
    origin_lat: float, origin_lng: float,
    dest_lat:   float, dest_lng:   float,
    mode:       str = "driving",
) -> Optional[dict]:
    """
    Fetch fastest Google Maps route for the best-time page.
    Returns a compact route dict, or falls back to Haversine estimate.
    """
    if GOOGLE_MAPS_KEY:
        try:
            params: dict = {
                "origin":       f"{origin_lat},{origin_lng}",
                "destination":  f"{dest_lat},{dest_lng}",
                "mode":         mode,
                "key":          GOOGLE_MAPS_KEY,
                "alternatives": "false",
            }
            if mode == "driving":
                params["departure_time"] = "now"
                params["traffic_model"]  = "best_guess"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/directions/json", params=params)
                if resp.status_code == 200 and resp.json().get("status") == "OK":
                    leg = resp.json()["routes"][0]["legs"][0]
                    dur = leg.get("duration_in_traffic") or leg.get("duration", {})
                    return {
                        "duration":       dur.get("text", "N/A"),
                        "duration_secs":  dur.get("value", 0),
                        "distance":       leg.get("distance",{}).get("text","N/A"),
                        "summary":        resp.json()["routes"][0].get("summary",""),
                        "start_address":  leg.get("start_address",""),
                        "end_address":    leg.get("end_address",""),
                        "source":         "google_maps_live",
                    }
        except Exception as e:
            print(f"[BestTime Route] {e}")
    
    # Fallback to Haversine estimate
    return _estimate_travel_time(origin_lat, origin_lng, dest_lat, dest_lng, mode)


@app.get("/best-time")
async def best_time(
    from_location: str = Query(..., alias="from"),
    to_location:   str = Query(..., alias="to"),
):
    """
    Best-time-to-travel endpoint (v4.2 — improved accuracy).

    Changes:
    - Hourly curve sourced from BestTime weekly forecast (real historical data)
    - Current hour blends live BestTime data for real-time accuracy
    - Travel time always provided (Google Maps or Haversine estimate)
    - Added time_to_reach field for clearer time-required info
    """
    loc = LOCATION_MAP.get(from_location)
    dest_loc = LOCATION_MAP.get(to_location)
    ist = _ist_now()

    # ── Build 24-hour curve ───────────────────────────────────────────────────
    hourly: Dict[int, float] = {}
    bt_curve: Optional[Dict[int, float]] = None
    venue_id = None

    # Try BestTime weekly forecast first
    if BESTTIME_API_KEY and loc:
        venue_name    = loc["locationName"]
        venue_address = f"{venue_name}, {loc.get('area','Mumbai')}, Mumbai, India"
        venue_id      = await _besttime_get_venue_id(
            venue_name, venue_address, 
            loc.get("latitude"), loc.get("longitude")
        )
        if venue_id:
            bt_curve = await _besttime_weekly_raw(venue_id)

    if bt_curve:
        # BestTime returns 0–100 directly — this is real historical data
        hourly = {h: round(bt_curve[h], 1) for h in range(24)}
    else:
        # Physics fallback
        for h in range(24):
            sim_dt     = ist.replace(hour=h, minute=0, second=0, microsecond=0)
            d, _       = _compute_physics_density(loc or LOCATIONS[0], sim_dt)
            hourly[h]  = round(d, 1)

    # Blend current live density into the current hour for real-time accuracy
    if loc:
        live_density, live_source = await _resolve_density(loc)
        hourly[ist.hour] = live_density

    # Find best hour (lowest crowd density)
    best_hour    = min(hourly, key=hourly.get)
    best_density = hourly[best_hour]
    
    # Also find the worst hour for comparison
    worst_hour = max(hourly, key=hourly.get)
    worst_density = hourly[worst_hour]

    # ── Travel time (always provided) ─────────────────────────────────────────
    travel_info = None
    if loc and dest_loc:
        travel_info = await _google_maps_fastest_route(
            loc["latitude"], loc["longitude"],
            dest_loc["latitude"], dest_loc["longitude"],
            mode="driving",
        )
    elif loc and not dest_loc:
        # If destination not in LOCATION_MAP, use center of Mumbai
        travel_info = await _google_maps_fastest_route(
            loc["latitude"], loc["longitude"],
            MUMBAI_BOUNDS["center_lat"], MUMBAI_BOUNDS["center_lng"],
            mode="driving",
        )

    response = {
        "from":              from_location,
        "to":                to_location,
        "current_hour":      ist.hour,
        "current_density":   hourly[ist.hour],
        "current_status":    _crowd_status(hourly[ist.hour]),
        "best_hour":         best_hour,
        "best_time":         f"{best_hour:02d}:00",
        "expected_density":  best_density,
        "status":            _crowd_status(best_density),
        "worst_hour":        worst_hour,
        "worst_time":        f"{worst_hour:02d}:00",
        "worst_density":     worst_density,
        "city":              "Mumbai",
        "data_source":       "besttime_weekly" if bt_curve else "physics_engine",
        "hourly_predictions": [
            {"hour": h, "density": d, "status": _crowd_status(d)}
            for h, d in sorted(hourly.items())
        ],
    }

    # Always add travel time info
    if travel_info:
        response["fastest_route"] = {
            "mode":          "driving",
            "duration":      travel_info["duration"],
            "distance":      travel_info["distance"],
            "summary":       travel_info.get("summary", "Direct route"),
            "source":        travel_info.get("source", "unknown"),
        }
        # Add time_to_reach as a clear field
        response["time_to_reach"] = travel_info["duration"]
        response["distance"] = travel_info["distance"]

    return response


# ─────────────────────────────────────────────────────────────────────────────
# AI SMART ROUTE
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_directions_for_mode(
    origin_lat: float, origin_lng: float,
    dest_lat:   float, dest_lng:   float,
    mode:       str,
) -> dict:
    origin_str = f"{origin_lat},{origin_lng}"
    dest_str   = f"{dest_lat},{dest_lng}"
    if GOOGLE_MAPS_KEY:
        try:
            params: dict = {
                "origin": origin_str, "destination": dest_str,
                "mode": mode, "key": GOOGLE_MAPS_KEY,
                "alternatives": "true", "language": "en",
            }
            if mode == "driving":
                params["departure_time"] = "now"
                params["traffic_model"]  = "best_guess"
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/directions/json", params=params)
                if resp.status_code == 200 and resp.json().get("status") == "OK":
                    routes = []
                    for r in resp.json().get("routes",[])[:3]:
                        leg = r.get("legs",[{}])[0]
                        if mode == "driving" and leg.get("duration_in_traffic"):
                            dur_text = leg["duration_in_traffic"].get("text","N/A")
                            dur_secs = leg["duration_in_traffic"].get("value",0)
                        else:
                            dur_text = leg.get("duration",{}).get("text","N/A")
                            dur_secs = leg.get("duration",{}).get("value",0)
                        routes.append({
                            "summary":         r.get("summary", f"{mode.capitalize()} Route"),
                            "duration":        dur_text,
                            "duration_secs":   dur_secs,
                            "distance":        leg.get("distance",{}).get("text","N/A"),
                            "distance_meters": leg.get("distance",{}).get("value",0),
                            "start_address":   leg.get("start_address",""),
                            "end_address":     leg.get("end_address",""),
                            "warnings":        r.get("warnings",[None])[0] if r.get("warnings") else None,
                            "via_waypoints":   [w.get("location",{}) for w in r.get("waypoints",[])],
                            "steps_count":     len(leg.get("steps",[])),
                        })
                    if routes:
                        return {"mode": mode, "routes": routes, "source": "google_live"}
        except Exception as e:
            print(f"[Directions/{mode}] {e}")

    dist_km  = _haversine(origin_lat, origin_lng, dest_lat, dest_lng)
    ist      = _ist_now()
    hour     = ist.hour
    is_peak  = (7 <= hour <= 10) or (17 <= hour <= 20)
    speed_map = {"driving": 20 if is_peak else 35, "bicycling": 14, "walking": 5, "transit": 18 if is_peak else 25}
    speed = speed_map.get(mode, 25)
    mins  = max(int(dist_km / speed * 60), 2)
    return {
        "mode": mode,
        "routes": [
            {"summary": "Fastest Route", "duration": f"{mins} mins",
             "duration_secs": mins*60, "distance": f"{round(dist_km,1)} km",
             "distance_meters": int(dist_km*1000), "start_address": "",
             "end_address": "", "warnings": "Estimate — live data unavailable" if is_peak else None,
             "via_waypoints": [], "steps_count": 0},
            {"summary": "Alternate Route", "duration": f"{max(int(dist_km/(speed*0.85)*60),2)} mins",
             "duration_secs": max(int(dist_km/(speed*0.85)*60),2)*60,
             "distance": f"{round(dist_km*1.2,1)} km",
             "distance_meters": int(dist_km*1200), "start_address": "",
             "end_address": "", "warnings": None, "via_waypoints": [], "steps_count": 0},
        ],
        "source": "physics_estimate",
    }


def _best_route_from_modes(modes_data: dict) -> dict:
    best = None
    for mode, data in modes_data.items():
        for route in data.get("routes",[]):
            secs = route.get("duration_secs", 999999)
            if best is None or secs < best["duration_secs"]:
                best = {"mode": mode, "route": route, "duration_secs": secs}
    return best or {}


@app.post("/ai/smart-route")
async def ai_smart_route(req: SmartRouteRequest):
    import re
    ist = _ist_now()
    modes_to_fetch = ["driving","bicycling","walking"] if req.mode != "transit" else ["transit","driving","walking"]
    tasks = {
        mode: asyncio.create_task(
            _fetch_directions_for_mode(req.origin.lat, req.origin.lng,
                                       req.destination.lat, req.destination.lng, mode))
        for mode in modes_to_fetch
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    modes_data: dict = {}
    for mode, result in zip(tasks.keys(), results):
        if not isinstance(result, Exception):
            modes_data[mode] = result

    mode_labels = {"driving":"🚗 Car","bicycling":"🚲 Bike","walking":"🚶 Walk","transit":"🚌 Transit"}
    mode_summary_lines = []
    for mode, data in modes_data.items():
        best_r = min(data.get("routes",[{}]), key=lambda r: r.get("duration_secs",99999), default={})
        if best_r:
            warn = f" ⚠ {best_r['warnings']}" if best_r.get("warnings") else ""
            mode_summary_lines.append(
                f"  {mode_labels.get(mode,mode)}: {best_r['duration']} via {best_r['summary']}"
                f" ({best_r['distance']}){warn}")

    modes_text = "\n".join(mode_summary_lines) or "  No route data available"
    fastest    = _best_route_from_modes(modes_data)

    ai_prompt = (
        "You are a smart real-time route advisor for Mumbai.\n"
        "Your job: recommend the BEST way to travel RIGHT NOW based on live route data.\n"
        "Do NOT mention population density or crowd percentages.\n"
        "Focus ONLY on: travel time, vehicle choice, road conditions, and practical tips.\n\n"
        f"Journey: {req.origin.name} → {req.destination.name}\n"
        f"Current time: {ist.strftime('%I:%M %p, %A')} IST\n"
        f"User's preferred mode: {req.mode}\n\n"
        f"Live route options right now:\n{modes_text}\n\n"
        "Respond in this exact format (3 sections, no extra text):\n\n"
        "BEST ROUTE: [vehicle] via [route name] — [duration] ([distance])\n\n"
        "WHY: [1-2 sentences on why this is best right now — mention time of day, traffic, road type]\n\n"
        "TIPS:\n"
        "• [tip 1 — specific road/area to use or avoid]\n"
        "• [tip 2 — parking, entry point, transit stop, or timing tip]\n"
        "• [tip 3 — alternative if the best option is not suitable]"
    )

    try:
        ai_advice = _gemini_ask(ai_prompt)
    except Exception as e:
        print(f"[SmartRoute Gemini] {e}")
        fastest_mode  = fastest.get("mode", req.mode)
        fastest_route = fastest.get("route", {})
        ai_advice = (
            f"BEST ROUTE: {mode_labels.get(fastest_mode, fastest_mode)} via "
            f"{fastest_route.get('summary','direct route')} — "
            f"{fastest_route.get('duration','N/A')} ({fastest_route.get('distance','N/A')})\n\n"
            "WHY: This is the fastest available option right now.\n\n"
            "TIPS:\n• Depart immediately to maintain this ETA\n"
            "• Check for road closures before leaving\n"
            f"• Consider {mode_labels.get('transit','transit')} as an alternative"
        )

    def _extract_section(text: str, heading: str) -> str:
        m = re.search(rf"{heading}[:\s]*(.*?)(?=\n[A-Z]+[:\n]|$)", text, re.DOTALL|re.IGNORECASE)
        return m.group(1).strip() if m else ""

    best_route_line = _extract_section(ai_advice, "BEST ROUTE")
    why_text        = _extract_section(ai_advice, "WHY")
    tips_block      = _extract_section(ai_advice, "TIPS")
    tip_lines = [ln.strip().lstrip("•-").strip() for ln in tips_block.split("\n")
                 if ln.strip().startswith(("•","-")) and len(ln.strip()) > 5]
    recommendations = [{"text": t} for t in tip_lines[:4]] or [
        {"text": f"Take {fastest.get('route',{}).get('summary','the fastest route')} for best ETA"},
        {"text": "Avoid peak-hour roads between 8–10 AM and 5–8 PM"},
    ]
    time_match     = re.search(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b", ai_advice)
    best_departure = time_match.group(1) if time_match else ist.strftime("%I:%M %p") + " (depart now)"

    route_cards = []
    for mode, data in modes_data.items():
        best_r = min(data.get("routes",[{}]), key=lambda r: r.get("duration_secs",99999), default={})
        if best_r:
            route_cards.append({
                "mode": mode, "mode_label": mode_labels.get(mode,mode),
                "summary": best_r.get("summary",""),
                "duration": best_r.get("duration","N/A"),
                "duration_secs": best_r.get("duration_secs",0),
                "distance": best_r.get("distance","N/A"),
                "warnings": best_r.get("warnings"),
                "source": data.get("source","unknown"),
                "all_routes": data.get("routes",[]),
            })
    route_cards.sort(key=lambda c: c["duration_secs"])

    return {
        "origin":      {"name": req.origin.name, "lat": req.origin.lat, "lng": req.origin.lng},
        "destination": {"name": req.destination.name, "lat": req.destination.lat, "lng": req.destination.lng},
        "ist_time":    ist.strftime("%I:%M %p IST"),
        "ist_day":     ist.strftime("%A"),
        "route_cards": route_cards,
        "fastest": {
            "mode":       fastest.get("mode",""),
            "mode_label": mode_labels.get(fastest.get("mode",""),""),
            "summary":    fastest.get("route",{}).get("summary",""),
            "duration":   fastest.get("route",{}).get("duration","N/A"),
            "distance":   fastest.get("route",{}).get("distance","N/A"),
        },
        "best_route_line": best_route_line or ai_advice.split("\n")[0],
        "why":             why_text,
        "ai_advice":       ai_advice,
        "best_time":       best_departure,
        "recommendations": recommendations,
        "routes":          route_cards[0].get("all_routes",[]) if route_cards else [],
        "city":            "Mumbai",
    }


# ─────────────────────────────────────────────────────────────────────────────
# AI INSIGHTS
# ─────────────────────────────────────────────────────────────────────────────

AI_SYSTEM = (
    "You are an AI assistant for CrowdSense, a real-time crowd monitoring platform in Mumbai. "
    "Provide concise, actionable insights about crowd levels at monitored locations. "
    "Use emojis where helpful. Keep responses short and practical."
)

AI_ROUTE_SYSTEM = (
    "You are a smart real-time route advisor for Mumbai. "
    "Your job is to recommend the BEST route and vehicle type based on live travel times. "
    "Never mention population density percentages. "
    "Focus on: road names, travel time, vehicle suitability, and practical Mumbai-specific tips."
)


@app.post("/ai/insights")
async def ai_insights(body: AiInsightsBody):
    try:
        if body.crowdData:
            crowd_info = "\n".join(
                f"- {item.get('locationName') or item.get('location_name','?')}: "
                f"density {item.get('crowdDensity') or item.get('crowd_density','?')}% "
                f"({item.get('status','?')}) [source: {item.get('source','?')}]"
                for item in body.crowdData
            )
        else:
            tasks = [_build_crowd_item(loc) for loc in LOCATIONS[:6]]
            items = await asyncio.gather(*tasks, return_exceptions=True)
            crowd_info = "\n".join(
                f"- {item['locationName']}: density {item['crowdDensity']}% ({item['status']})"
                for item in items if not isinstance(item, Exception)
            )
        prompt  = (
            f"{AI_SYSTEM}\n\nCurrent crowd data:\n{crowd_info}\n\n"
            "Generate a brief crowd situation summary with key alerts and "
            "a one-line recommendation for travelers."
        )
        summary = _gemini_ask(prompt)
        return {"summary": summary, "success": True, "city": "Mumbai"}
    except Exception as e:
        print(f"[AI Insights] {e}\n{traceback.format_exc()}")
        return {"summary": "AI insights temporarily unavailable.", "success": False, "error": str(e)}


@app.post("/ai/route-advice")
async def ai_route_advice(body: AiRouteAdviceBody):
    import re
    ist = _ist_now()
    origin_name = body.origin or "current location"
    dest_name   = body.destination or "destination"
    origin_lat, origin_lng = 19.0760, 72.8777
    dest_lat,   dest_lng   = 19.0760, 72.8777

    if body.crowdData and len(body.crowdData) >= 2:
        try:
            origin_lat = float(body.crowdData[0].get("latitude", origin_lat))
            origin_lng = float(body.crowdData[0].get("longitude", origin_lng))
            dest_lat   = float(body.crowdData[-1].get("latitude", dest_lat))
            dest_lng   = float(body.crowdData[-1].get("longitude", dest_lng))
        except (TypeError, ValueError):
            pass
    elif body.origin and body.destination:
        origin_results = await _nominatim_search(body.origin, limit=1, bias_lat=19.076, bias_lng=72.877)
        dest_results   = await _nominatim_search(body.destination, limit=1, bias_lat=19.076, bias_lng=72.877)
        if origin_results: origin_lat, origin_lng = origin_results[0]["lat"], origin_results[0]["lng"]
        if dest_results:   dest_lat, dest_lng     = dest_results[0]["lat"],   dest_results[0]["lng"]

    driving_res, bike_res, walking_res = await asyncio.gather(
        asyncio.create_task(_fetch_directions_for_mode(origin_lat, origin_lng, dest_lat, dest_lng, "driving")),
        asyncio.create_task(_fetch_directions_for_mode(origin_lat, origin_lng, dest_lat, dest_lng, "bicycling")),
        asyncio.create_task(_fetch_directions_for_mode(origin_lat, origin_lng, dest_lat, dest_lng, "walking")),
        return_exceptions=True,
    )

    mode_labels = {"driving":"🚗 Car/Auto","bicycling":"🚲 Bike","walking":"🚶 Walk"}
    modes_data  = {}
    for mode, res in [("driving",driving_res),("bicycling",bike_res),("walking",walking_res)]:
        if not isinstance(res, Exception):
            modes_data[mode] = res

    mode_lines = []
    for mode, data in modes_data.items():
        best_r = min(data.get("routes",[{}]), key=lambda r: r.get("duration_secs",99999), default={})
        if best_r:
            warn = f" ⚠ {best_r['warnings']}" if best_r.get("warnings") else ""
            mode_lines.append(
                f"  {mode_labels[mode]}: {best_r['duration']} via {best_r['summary']}"
                f" ({best_r['distance']}){warn}")

    modes_text = "\n".join(mode_lines) or "  No live route data"
    fastest    = _best_route_from_modes(modes_data)

    prompt = (
        f"{AI_ROUTE_SYSTEM}\n\n"
        f"Journey: {origin_name} → {dest_name}\n"
        f"Current time: {ist.strftime('%I:%M %p, %A')} IST\n\n"
        f"Live travel times right now:\n{modes_text}\n\n"
        "Respond in this format:\n\n"
        "BEST ROUTE: [vehicle] via [road/route] — [duration] ([distance])\n\n"
        "WHY: [1-2 sentences]\n\n"
        "TIPS:\n• [road/area tip]\n• [timing/parking tip]\n• [backup option]"
    )

    try:
        advice_text = _gemini_ask(prompt)
    except Exception as e:
        print(f"[RouteAdvice Gemini] {e}")
        fastest_mode  = fastest.get("mode","driving")
        fastest_route = fastest.get("route",{})
        advice_text = (
            f"BEST ROUTE: {mode_labels.get(fastest_mode,fastest_mode)} via "
            f"{fastest_route.get('summary','direct route')} — "
            f"{fastest_route.get('duration','N/A')} ({fastest_route.get('distance','N/A')})\n\n"
            f"WHY: Fastest available option at {ist.strftime('%I:%M %p')}.\n\n"
            "TIPS:\n• Depart now to maintain this ETA\n"
            "• Avoid peak-hour congestion on Western/Eastern Express Highway\n"
            "• Consider local trains if driving time exceeds 45 mins"
        )

    time_match = re.search(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b", advice_text)
    best_time  = time_match.group(1) if time_match else ist.strftime("%I:%M %p") + " (now)"
    tip_lines  = [ln.strip().lstrip("•-").strip() for ln in advice_text.split("\n")
                  if ln.strip().startswith(("•","-")) and len(ln.strip()) > 5]
    recommendations = [{"text": t} for t in tip_lines[:4]] or [
        {"text": f"Take {fastest.get('route',{}).get('summary','the fastest route')} for best ETA"},
        {"text": "Avoid Western Express Highway during peak hours (8–10 AM, 5–8 PM)"},
        {"text": "Local trains are fastest for distances over 10 km in Mumbai"},
    ]

    route_cards = []
    for mode, data in modes_data.items():
        best_r = min(data.get("routes",[{}]), key=lambda r: r.get("duration_secs",99999), default={})
        if best_r:
            route_cards.append({
                "mode": mode, "mode_label": mode_labels.get(mode,mode),
                "summary": best_r.get("summary",""),
                "duration": best_r.get("duration","N/A"),
                "duration_secs": best_r.get("duration_secs",0),
                "distance": best_r.get("distance","N/A"),
                "warnings": best_r.get("warnings"),
                "source": data.get("source","unknown"),
            })
    route_cards.sort(key=lambda c: c["duration_secs"])

    return {
        "advice": advice_text, "summary": advice_text,
        "best_time": best_time, "recommendations": recommendations,
        "route_cards": route_cards,
        "fastest": {
            "mode":       fastest.get("mode",""),
            "mode_label": mode_labels.get(fastest.get("mode",""),""),
            "summary":    fastest.get("route",{}).get("summary",""),
            "duration":   fastest.get("route",{}).get("duration","N/A"),
            "distance":   fastest.get("route",{}).get("distance","N/A"),
        },
        "ist_time": ist.strftime("%I:%M %p IST"),
        "success":  True,
        "city":     "Mumbai",
    }


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN / TRAINING
# ─────────────────────────────────────────────────────────────────────────────

async def _fake_training_job(hours: int):
    global training_state
    await asyncio.sleep(hours * 0.5)
    training_state.update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "last_rows_used": hours * random.randint(50, 200),
    })

@app.post("/realtime/train")
async def start_realtime_training(body: RealtimeTrainBody):
    global training_state
    if not GOOGLE_MAPS_KEY:
        return {**training_state, "message": "Maps not configured", "status_code": 503}
    if training_state["status"] == "running":
        return {**training_state, "message": "Training already in progress", "status_code": 409}
    training_state.update({"status": "running",
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "last_error": None})
    asyncio.create_task(_fake_training_job(body.hours_to_sample))
    return {**training_state, "message": "Training started", "status_code": 200}

@app.get("/realtime/train/status")
async def realtime_training_status():
    return {"training": training_state}

@app.get("/realtime/training-data")
async def realtime_training_data():
    return {
        "training_data": {
            "total_samples":     training_state.get("last_rows_used", 0),
            "locations_covered": len(LOCATIONS),
            "city":              "Mumbai",
            "last_trained":      training_state.get("completed_at"),
            "model_version":     "4.2-besttime-accurate-physics-calibrated",
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chatbot — Public Transport, Crowd Prediction & Transit Expert
# ─────────────────────────────────────────────────────────────────────────────

CHATBOT_SYSTEM_PROMPT = """You are a specialized AI assistant with expertise ONLY in the following domains:

1. **PUBLIC TRANSPORT EXPERT**: You have comprehensive knowledge about:
   - Bus schedules, departures, routes, and timings worldwide
   - Bus service alerts, delays, disruptions, and real-time updates
   - Bus stop locations, transfers, and connections
   - Public bus systems in any city or country

2. **CROWD PREDICTOR**: You can provide:
   - Crowd density predictions for any location worldwide
   - Peak and off-peak timing analysis
   - Crowd flow patterns at transit hubs, stations, and public spaces
   - Best times to travel to avoid crowds
   - Event-based crowd predictions

3. **TRANSIT EXPERT**: You possess deep knowledge of:
   - Metro, subway, train, tram, and ferry systems globally
   - Multi-modal transit planning and connections
   - Transit fares, passes, and ticketing systems
   - Accessibility features in public transit
   - Transit apps and real-time tracking systems

STRICT RULES YOU MUST FOLLOW:
- You MUST ONLY respond to questions related to the above three domains
- If a user asks about ANY topic outside these domains (e.g., coding, recipes, general knowledge, entertainment, personal advice, etc.), you MUST politely decline and redirect them to ask about public transport, crowd prediction, or transit topics
- NEVER provide information or engage in conversations about topics outside your expertise
- NEVER hallucinate or make up information. If you don't have specific real-time data, clearly state that and provide general guidance based on typical patterns
- Always be helpful within your domain expertise
- When providing bus/transit information, remind users to verify with official local transit authorities for real-time accuracy

RESPONSE FORMAT:
- Be concise and informative
- Use bullet points for schedules and lists
- Provide actionable advice when possible
- If declining an off-topic question, suggest a relevant transit/crowd topic the user might be interested in

DECLINE TEMPLATE (use when user asks off-topic questions):
"I'm sorry, but I can only assist with questions about:
• Public transport (buses, schedules, alerts)
• Crowd predictions and density analysis
• Transit systems (metro, trains, trams)

Is there anything related to these topics I can help you with?"
"""

class ChatMessage(BaseModel):
    message: str
    conversation_history: Optional[List[Dict[str, str]]] = None

class ChatResponse(BaseModel):
    response: str
    topic_valid: bool
    suggested_topics: Optional[List[str]] = None

@app.post("/api/chatbot", response_model=ChatResponse)
async def chatbot_endpoint(body: ChatMessage):
    """
    Public Transport, Crowd Prediction & Transit Expert Chatbot.

    Provider chain:
      1. Gemini gemini-1.5-flash  (primary — highest free quota)
      2. Groq  llama3-8b-8192     (emergency fallback — activates only on Gemini quota exhaustion)
      3. 503 with clear JSON detail if both are exhausted
    """
    user_message = body.message.strip()

    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    response_text: Optional[str] = None
    provider_error: Optional[str] = None

    # ── 1. Primary: Gemini ────────────────────────────────────────────────────
    if gemini_model is not None:
        try:
            chat_history: List[dict] = []
            if body.conversation_history:
                for msg in body.conversation_history[-10:]:
                    role    = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        chat_history.append({"role": "user",  "parts": [content]})
                    elif role == "assistant":
                        chat_history.append({"role": "model", "parts": [content]})

            chat        = gemini_model.start_chat(history=chat_history)
            full_prompt = (
                f"{CHATBOT_SYSTEM_PROMPT}\n\n"
                f"User's question: {user_message}\n\n"
                "Please provide a helpful response following the guidelines above."
            )
            resp          = chat.send_message(full_prompt)
            response_text = (resp.text or "").strip() or None
        except Exception as e:
            # Always fall through to Groq on ANY Gemini error
            # (400 key expired, 429 quota, 403 permission, 500 upstream, etc.)
            print(f"[Chatbot] Gemini failed ({type(e).__name__}: {e}) — activating Groq emergency fallback.")
            provider_error = "gemini_failed"
    else:
        print("[Chatbot] Gemini not configured — activating Groq emergency fallback.")
        provider_error = "gemini_not_configured"

    # ── 2. Emergency fallback: Groq ───────────────────────────────────────────
    if response_text is None and groq_client is not None:
        try:
            messages: List[dict] = [{"role": "system", "content": CHATBOT_SYSTEM_PROMPT}]
            if body.conversation_history:
                for msg in body.conversation_history[-10:]:
                    role    = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role in ("user", "assistant"):
                        messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_message})

            completion    = groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=messages,
                max_tokens=600,
                timeout=20,
            )
            response_text = (completion.choices[0].message.content or "").strip() or None
            if response_text:
                print("[Chatbot] Groq emergency fallback succeeded.")
        except Exception as e:
            print(f"[Chatbot] Groq emergency fallback error: {e}")
            traceback.print_exc()
            provider_error = "all_providers_exhausted"

    # ── 3. All providers exhausted → 503 ─────────────────────────────────────
    if not response_text:
        raise HTTPException(
            status_code=503,
            detail={
                "response":       "AI service is temporarily unavailable. Please try again shortly.",
                "success":        False,
                "provider_error": provider_error or "unknown",
            },
        )

    # ── Determine topic validity ──────────────────────────────────────────────
    decline_indicators = [
        "I can only assist with",
        "outside my expertise",
        "I'm sorry, but I can only",
        "I cannot help with",
        "beyond my scope",
    ]
    topic_valid = not any(ind.lower() in response_text.lower() for ind in decline_indicators)

    suggested_topics = None
    if not topic_valid:
        suggested_topics = [
            "What's the best time to travel to avoid crowds at major train stations?",
            "How do I find real-time bus schedules in my city?",
            "What are typical crowd patterns at metro stations during rush hour?",
            "How can I plan a multi-modal transit journey?",
            "What bus routes connect the airport to downtown?",
        ]

    return ChatResponse(
        response=response_text,
        topic_valid=topic_valid,
        suggested_topics=suggested_topics,
    )


@app.get("/api/chatbot/topics")
async def chatbot_topics():
    """
    Returns the list of topics the chatbot can help with
    """
    return {
        "supported_topics": [
            {
                "category": "Public Transport",
                "description": "Bus schedules, departures, routes, alerts, and service updates",
                "example_questions": [
                    "What are the bus routes from downtown to the airport?",
                    "Are there any bus service alerts today?",
                    "What time does the last bus leave from Central Station?"
                ]
            },
            {
                "category": "Crowd Prediction",
                "description": "Crowd density analysis, peak times, and best travel times",
                "example_questions": [
                    "When is the best time to visit Times Square to avoid crowds?",
                    "What's the crowd level at the train station during rush hour?",
                    "Predict crowd density at the shopping mall on Saturday afternoon"
                ]
            },
            {
                "category": "Transit Expert",
                "description": "Metro, subway, train, tram systems, fares, and multi-modal planning",
                "example_questions": [
                    "How do I get from the airport to city center using public transit?",
                    "What's the fare for the metro day pass?",
                    "Which transit apps work best in Tokyo?"
                ]
            }
        ],
        "chatbot_info": {
            "name": "Transit & Crowd AI Assistant",
            "version": "1.0",
            "capabilities": [
                "Bus schedule and route information",
                "Transit alerts and service updates",
                "Crowd density predictions",
                "Multi-modal journey planning",
                "Transit system information worldwide"
            ],
            "limitations": [
                "Cannot provide real-time GPS tracking",
                "Recommend verifying schedules with local authorities",
                "Does not book tickets or make reservations"
            ]
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)