# Train Seat Map

Web app to view IRCTC train seat maps by quota, with occupancy stats, berth-level booking details, and vacant seat finder between any two stations.

## Features

- Search any train by number and view full schedule
- View coach-wise seat map with berth layout (1A/2A/3A/SL)
- Color-coded seats by quota (GN, TQ, PT, LD, etc.)
- Click any berth to see full booking segment details
- Occupancy stats and Quota x Berth Type cross-tabulation
- Summary grouped by coach class type
- Find vacant berths between any two stations on the route
- In-memory API response caching with configurable TTLs

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn app:app --reload
```

Open http://localhost:8000

## How it works

1. Enter a train number to fetch the schedule
2. Select boarding station and date, then get coach list
3. Click a coach or "Fetch All Coaches" to view seat maps
4. Use "Find Vacant Berths" to search availability between stations

## Tech Stack

- **Backend**: FastAPI + Jinja2
- **Frontend**: Vanilla HTML/CSS/JS (single-page)
- **Data**: IRCTC public APIs (requires active session cookies)

## License

MIT
