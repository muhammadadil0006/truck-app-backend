# ELD Trip Planner — Backend

Django + Django REST Framework API. See [`../PLANNING.md`](../PLANNING.md) for
the full architecture and API contract, and [`../CLAUDE.md`](../CLAUDE.md) for
the HOS rules this implements.

## Stack

- Django 6.1 + Django REST Framework
- SQLite locally, Postgres in production
- OpenRouteService for geocoding + directions
- No Celery, no Redis (see `../PLANNING.md` § Architecture Decisions for why)

## Local Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.sample .env
# Edit .env: set a real SECRET_KEY (see below) and your ORS_API_KEY

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

API is now live at `http://localhost:8000/api/`. Browsable DRF API at the
same URLs in a browser (enabled only when `DEBUG=True`).

Generate a real `SECRET_KEY`:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Getting an OpenRouteService API key

1. Sign up free at https://openrouteservice.org/dev/#/signup (email only, no
   card required).
2. Create a token, paste it into `.env` as `ORS_API_KEY`.
3. Free tier: 2,000 requests/day — plenty for development and demoing.

## Environment Variables

| Variable | Local default | Production (Render) |
|---|---|---|
| `SECRET_KEY` | any string | real generated secret, kept out of git |
| `DEBUG` | `True` | `False` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | your Render domain |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | Render's managed Postgres URL (auto-injected) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://localhost:3000` | your deployed Vercel URL(s) |
| `ORS_API_KEY` | your free ORS key | same |
| `ORS_BASE_URL` | `https://api.openrouteservice.org` | same |

See `.env.sample` for the full template.

## Project Structure

```
backend/
├── config/          # Django project: settings.py, urls.py
├── trips/           # the one Django app: models, serializers, views, urls, tests
└── services/        # framework-agnostic logic, testable without Django/DB
    ├── constants.py     # every HOS threshold — single source of truth
    ├── hos_engine/      # the trip-planning simulator (services/hos_engine/engine.py)
    └── routing/         # OpenRouteService client wrapper
```

## Running Tests

```bash
python manage.py test
```

`trips/tests/test_hos_engine.py` reuses the 5 worked examples from
`../ALGORITHM-GUIDE.md` as end-to-end test cases — this is the
highest-value test file since accuracy is the top grading criterion.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/geocode/?q=<text>` | Location autocomplete (proxied to ORS — see below) |
| `POST` | `/api/trips/` | Plan a trip (route → HOS simulation → persist; locations already resolved) |
| `GET` | `/api/trips/` | Trip history (lightweight list) |
| `GET` | `/api/trips/<uuid>/` | Retrieve one trip in full (shareable link) |
| `DELETE` | `/api/trips/<uuid>/` | Remove a trip from history |

**Why a geocode proxy endpoint**: the frontend never geocodes free text
itself, and never calls ORS directly (that would leak `ORS_API_KEY` into the
browser bundle). `LocationAutocomplete.tsx` calls `/api/geocode/` as the
user types; selecting a suggestion locks in its exact `lat`/`lng`, which is
what actually gets submitted in `POST /api/trips/`. This means location text
is only ever geocoded once, by one service, so the point shown in the UI is
guaranteed to be the point the route is computed from.

Full request/response shapes in [`../PLANNING.md`](../PLANNING.md) § API Contract.

## Deploying to Render

1. Push this repo to GitHub (already connected — see project notes).
2. In the Render dashboard: **New → Web Service**, connect the repo, set
   **Root Directory** to `backend`.
3. Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
4. Start command: `gunicorn config.wsgi:application`
5. Add a **New → PostgreSQL** instance (free tier); Render auto-injects
   `DATABASE_URL` into the web service if they're linked in the same
   dashboard — otherwise copy its connection string into the web service's
   env vars manually.
6. Set environment variables in the Render dashboard: `SECRET_KEY` (generate
   a new one, don't reuse the local dev one), `DEBUG=False`, `ALLOWED_HOSTS`
   (your `*.onrender.com` domain), `ORS_API_KEY`, `CORS_ALLOWED_ORIGINS`
   (set once the frontend is deployed — see below).
7. Deploy. Note the resulting URL (e.g. `https://eld-trip-planner-api.onrender.com`).

**Free tier note**: the web service spins down after ~15 minutes idle and
cold-starts (~30–50s) on the next request — mention this in the Loom so a
slow first load during grading doesn't look broken.

## Connecting the Two Apps

Once both are deployed:
1. Copy the frontend's deployed Vercel URL (e.g. `https://eld-trip-planner.vercel.app`)
   into this backend's `CORS_ALLOWED_ORIGINS` env var on Render, redeploy.
2. Copy this backend's deployed Render URL + `/api/` into the frontend's
   `VITE_API_BASE_URL` env var on Vercel, redeploy (Vite bakes env vars in
   at build time — a redeploy is required after changing it).

See [`../frontend/README.md`](../frontend/README.md) for the frontend side
of this handoff.
