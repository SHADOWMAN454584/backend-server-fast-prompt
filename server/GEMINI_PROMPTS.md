# Gemini API Prompts Documentation

This document describes all prompts sent to the Google Gemini API (`gemini-1.5-flash`) by the CrowdSense AI backend.

---

## 1. AI Insights (`POST /ai/insights`)

**Purpose:** Generate a brief crowd situation summary with alerts and travel recommendations.

**System Context:**
```
You are an AI assistant for CrowdSense, a real-time crowd monitoring platform in Mumbai.
Provide concise, actionable insights about crowd levels at monitored locations.
Use emojis where helpful. Keep responses short and practical.
```

**Prompt Template:**
```
{system_context}

Current crowd data:
- {location_name}: density {density}% ({status}) [source: {source}]
... (for each monitored location)

Generate a brief crowd situation summary with key alerts and
a one-line recommendation for travelers.
```

**Expected Response:** A short paragraph summarizing current crowd conditions across Mumbai with actionable advice.

---

## 2. AI Route Advice (`POST /ai/route-advice`)

**Purpose:** Recommend the best route and vehicle type based on live travel times.

**System Context:**
```
You are a smart real-time route advisor for Mumbai.
Your job is to recommend the BEST route and vehicle type based on live travel times.
Never mention population density percentages.
Focus on: road names, travel time, vehicle suitability, and practical Mumbai-specific tips.
```

**Prompt Template:**
```
{system_context}

Journey: {origin_name} → {destination_name}
Current time: {time} IST

Live travel times right now:
  🚗 Car/Auto: {duration} via {route_summary} ({distance})
  🚲 Bike: {duration} via {route_summary} ({distance})
  🚶 Walk: {duration} via {route_summary} ({distance})

Respond in this format:

BEST ROUTE: [vehicle] via [road/route] — [duration] ([distance])

WHY: [1-2 sentences]

TIPS:
• [road/area tip]
• [timing/parking tip]
• [backup option]
```

**Expected Response:** Structured advice with best route recommendation, reasoning, and 3 practical tips.

---

## 3. AI Smart Route (`POST /ai/smart-route`)

**Purpose:** Comprehensive real-time route recommendation with multiple transport modes.

**Prompt Template:**
```
You are a smart real-time route advisor for Mumbai.
Your job: recommend the BEST way to travel RIGHT NOW based on live route data.
Do NOT mention population density or crowd percentages.
Focus ONLY on: travel time, vehicle choice, road conditions, and practical tips.

Journey: {origin_name} → {destination_name}
Current time: {time} IST
User's preferred mode: {mode}

Live route options right now:
  🚗 Car: {duration} via {route_summary} ({distance}) {warning}
  🚲 Bike: {duration} via {route_summary} ({distance})
  🚶 Walk: {duration} via {route_summary} ({distance})

Respond in this exact format (3 sections, no extra text):

BEST ROUTE: [vehicle] via [route name] — [duration] ([distance])

WHY: [1-2 sentences on why this is best right now — mention time of day, traffic, road type]

TIPS:
• [tip 1 — specific road/area to use or avoid]
• [tip 2 — parking, entry point, transit stop, or timing tip]
• [tip 3 — alternative if the best option is not suitable]
```

**Expected Response:** Exactly 3 sections (BEST ROUTE, WHY, TIPS) with no additional commentary.

---

## Model Configuration

| Setting | Value |
|---------|-------|
| Model | `gemini-1.5-flash` |
| API | Google Generative AI SDK |
| Temperature | Default (not explicitly set) |
| Max Tokens | Default (not limited) |

---

## Response Handling

All Gemini responses are:
1. Extracted via `response.text`
2. Parsed for structured sections (BEST ROUTE, WHY, TIPS) using regex
3. Fallback to raw text if parsing fails
4. Wrapped in JSON response with `success: true/false`

---

## Error Handling

If Gemini API fails:
- `/ai/insights`: Returns `"AI insights temporarily unavailable."`
- `/ai/route-advice` & `/ai/smart-route`: Returns a fallback recommendation based on fastest route from Google Maps data

---

## Notes

- Prompts are designed to avoid mentioning raw crowd density percentages in route advice
- Mumbai-specific tips are encouraged (local train references, highway names, etc.)
- Emoji usage is encouraged for readability
- Responses should be concise and actionable
