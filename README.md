# Weather-Aware Truck Routing

A React + Django web app that helps truck drivers evaluate alternative routes and choose the safest option based on forecast weather, load weight, and travel time.

Built for the Full Stack Developer assessment.

> 🌐 **Live Application:** [https://watr.gauravmehra.dev](https://watr.gauravmehra.dev/)  
> *(The domain prefix **`watr`** is an acronym for **W**eather-**A**ware **T**ruck **R**outing)*

- **Backend:** Django 5 + Django REST Framework (`backend/`)
- **Frontend:** React 19 + Vite + Leaflet (`frontend/`)
- **APIs:** OSRM (routing), Open-Meteo (weather forecasts), Photon (autocomplete), Nominatim (geocoding fallback)

---

## Quickstart

### Option 1: Docker (Production-ready)

Make sure Docker Desktop is running, then run:

```bash
docker compose up -d --build
# or: make docker-up
```

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **Logs:** `docker compose logs -f` (or `make docker-logs`)
- **Stop:** `docker compose down` (or `make docker-down`)

### Option 2: Local Development

```bash
make install   # sets up backend venv and installs npm packages
make migrate   # runs django migrations
make dev       # starts both backend (port 8001) and frontend (port 5173)
```

Run `make help` to see all available tasks.

---

## Project Structure

```
├── Makefile
├── docker-compose.yml
├── backend/
│   ├── config/              # Django settings, WSGI, URLs
│   ├── routing/
│   │   ├── views.py         # Endpoints: /api/plan/, /api/heatmap/, /api/places/, /api/health/
│   │   ├── serializers.py   # Request input validation
│   │   ├── services/
│   │   │   ├── planner.py       # Main pipeline tying routing, weather, risk & recommendations
│   │   │   ├── routing_api.py   # OSRM routing + perpendicular detour generation for 3 routes
│   │   │   ├── checkpoints.py   # 10/25/50 mile distance sampling & ETA interpolation
│   │   │   ├── weather.py       # Batched hourly forecast lookups (Open-Meteo)
│   │   │   ├── risk.py          # Threshold classification + load physics rules
│   │   │   ├── recommend.py     # Route ranking logic & tie-breaking
│   │   │   ├── heatmap.py       # Mercator corridor grid (0–48h window)
│   │   │   ├── places.py        # Photon search-as-you-type autocomplete
│   │   │   ├── geocoding.py     # Nominatim fallback geocoder
│   │   │   ├── geometry.py      # Douglas–Peucker route polyline simplification
│   │   │   ├── ratelimit.py     # Thread-safe rate limiter (OSM/Nominatim compliance)
│   │   │   └── errors.py        # User-facing domain exceptions
│   │   └── tests/           # 239 unit & integration tests (pytest)
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── api/client.js    # Fetch wrappers with user-friendly error formatting
    │   ├── lib/             # Risk styling, formatting helpers, canvas frame renderer
    │   ├── components/
    │   │   ├── TripForm.jsx         # Inputs for origin, destination, departure, load, interval
    │   │   ├── RouteCards.jsx       # Route comparison cards with risk breakdown
    │   │   ├── RouteMap.jsx         # Leaflet map, route polylines, checkpoints, pins, truck
    │   │   ├── HeatmapControls.jsx  # 0–48h slider, play/pause, layer switcher
    │   │   ├── HeatmapLayer.jsx     # Canvas frame overlay
    │   │   ├── CheckpointTable.jsx  # Collapsible checkpoint breakdown table
    │   │   └── PlaceInput.jsx       # ARIA-accessible combobox autocomplete
    │   ├── App.jsx
    │   └── index.css
    ├── package.json
    └── Dockerfile
```

---

## How It Works: Decisions & Assumptions

### 1. Generating 3 Route Options (`routing_api.py`)
- **Why OSRM over OpenRouteService:** OpenRouteService's public API limits alternative routing to trips under 100 km. Long-haul truck corridors are often 500–1,500+ miles. OSRM allows alternative routing at any distance and returns per-edge durations.
- **Detour fallback:** OSRM frequently returns only 1 or 2 routes for certain highway stretches. When that happens, the backend calculates perpendicular detour waypoints (offset by ±15% and ±30% of the trip length from the midpoint).
- **Candidate filters:** A detour route is only kept if it takes less than 1.5x the fastest route's duration and shares less than 80% road overlap with existing options (evaluated on a ~3.5-mile spatial grid).

### 2. Checkpoints & ETA Calculation (`checkpoints.py`)
- Checkpoints are sampled at the origin (mile 0), every 10 / 25 / 50 miles, and at the destination.
- If the destination is within 1.0 mile of the last interval checkpoint, they are merged to avoid near-duplicate markers.
- **Covered miles:** Each checkpoint "covers" the road closest to it (half the gap before + half the gap after). Their sum equals the total trip distance.
- **ETA interpolation:** OSRM per-edge durations are scaled to route total time to account for varied highway and urban speeds. Each checkpoint's arrival time is matched to the nearest hourly forecast time.

### 3. Weather Risk & Load Rules (`risk.py`)
Thresholds from the brief:
- **Wind:** Low (<25 mph), Moderate (25–34 mph), High (35–44 mph), Severe (45–54 mph), No Travel (≥55 mph).
- **Rain:** Low (<0.10 in/hr), Moderate (0.10–0.25 in/hr), High (0.25–0.50 in/hr), Severe (0.50–1.00 in/hr), No Travel (>1.00 in/hr).
- **Snow:** Low (<0.5 in/hr), Moderate (0.5–1.0 in/hr), High (1.0–2.0 in/hr), Severe (2.0–3.0 in/hr), No Travel (>3.0 in/hr).

**Cargo Weight Rules:**
- `≥55 mph` wind: No Travel regardless of weight.
- `45–54 mph` wind + `>30,000 lb`: Escalates to **No Travel** (rollover risk for heavy trailers).
- `35–44 mph` wind + `>40,000 lb`: Escalates to **Severe**.
- Checkpoint risk = `max(wind, rain, snow)`.
- *Boundary note:* Ranges include their lower bound (`0.25 in/hr` is High), but No Travel is strictly greater as specified in the brief (`>1.00 in/hr` rain, `>3.0 in/hr` snow).

### 4. Recommendation Logic (`recommend.py`)
Routes are ranked by:
1. **Fewest No Travel miles** (Safety first: a route with 5 miles of impassable/rollover weather should never beat one with 10 miles of severe weather).
2. **Fewest Severe miles**
3. **Fewest High miles**
4. **Lowest distance-weighted average risk** (Low=0 to No Travel=4)
5. **Shortest travel time**

If all routes have No Travel conditions, the app recommends the least dangerous option but marks `travel_advised: false` and displays a clear warning.

### 5. Corridor Heatmap & Performance (`heatmap.py`, `heat.js`)
- The corridor grid surrounds all routes and dynamically adjusts cell size (0.1° to 3.0°) so the entire trip corridor fits within 250 cells. This keeps Open-Meteo lookups under 3 batched requests.
- Rows are spaced in Web Mercator $y$, so the grid aligns with Leaflet map projection.
- **Fast scrubbing:** On arrival, all 49 hourly frames (0 to 48 hours) are rendered to off-screen canvas elements and pre-decoded as images. Scrubbing the slider simply swaps image URLs with zero network calls and no map re-renders.
- **Moving truck icon (🚚):** Interpolates truck position along the route based on elapsed hours.

### 6. Map Details (`RouteMap.jsx`)
- **Origin & Destination pins:** Green A (Start) and Red B (End) markers with full address tooltips.
- **Route tooltips on map:** Hovering or clicking any route polyline shows distance, duration, risk breakdown, and recommendation status.
- **On-map summary pill:** Floating card at the top-left gives live route stats.
- **Checkpoint toggle:** Users can view checkpoints for the active route or toggle all routes simultaneously.

---

## API Summary

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health/` | Liveness check |
| `POST` | `/api/plan/` | Calculates routes, checkpoints, weather risk & recommendation |
| `POST` | `/api/heatmap/` | Corridor weather grid for 0–48 hours |
| `GET` | `/api/places/?q=` | Autocomplete suggestions |

### `POST /api/plan/` Example
```json
{
  "origin": "Chicago, IL",
  "destination": "Denver, CO",
  "departure": "2026-10-31T08:00:00-05:00",
  "load_lb": 35000,
  "interval_miles": 25
}
```

Response includes geocoded locations, the recommended route ID with the decisive reason it won, and the full list of ranked routes with geometry and checkpoint weather data.

---

## Testing

```bash
# Run backend test suite (239 unit/integration tests with mocked services)
make test

# Run tests against live third-party APIs (OSRM, Open-Meteo, Photon, Nominatim)
make test-live

# Lint frontend
make lint

# Production build check
make build
```

---

## Engineering Considerations & Real-World Limitations

1. **OSRM Public Server:** The free demo OSRM server uses a standard car profile. Real commercial dispatch systems would connect to a truck-specific routing engine (e.g. OSRM truck profile or commercial APIs like HERE/Trimble) to account for bridge heights, weight limits, and truck speed limits.
2. **Open-Meteo Forecast Horizon:** Hourly forecasts are available up to 16 days out. Input departure time is validated to be within 13 days so the 48-hour heatmap window remains fully populated.
3. **Usage Policies & Rate Limiting:** Public Nominatim and OSRM servers request a maximum rate of 1 request/second and an identifying User-Agent. Calls are throttled via a thread-safe `RateLimiter` and geocoding responses are cached in memory for 24 hours.

---

## Author & Contact

**Gaurav Mehra**  
- **Live Demo:** [https://watr.gauravmehra.dev](https://watr.gauravmehra.dev/)  
  *(**WATR** stands for **W**eather-**A**ware **T**ruck **R**outing)*
- **Email:** [gauravmehra930@gmail.com](mailto:gauravmehra930@gmail.com)  
- **GitHub:** [https://github.com/Gauravmehra59/Weather-Aware-Truck-Routing](https://github.com/Gauravmehra59/Weather-Aware-Truck-Routing)  
