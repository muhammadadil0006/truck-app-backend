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

| Variable | Local default | Production (Vercel) |
|---|---|---|
| `SECRET_KEY` | any string | real generated secret, kept out of git |
| `DEBUG` | `True` | `False` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | your `*.vercel.app` domain (+ custom domain if any) |
| `CSRF_TRUSTED_ORIGINS` | unset | `https://your-backend.vercel.app` |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | Supabase Transaction pooler URL (port 6543) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://localhost:3000` | your deployed frontend URL(s) |
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

## Database: Supabase Postgres

1. Sign up free at https://supabase.com, **New Project** — set a DB
   password (save it, you need it for the connection string) and pick a
   region close to where you'll host the app.
2. Wait ~2 min for provisioning, then go to **Project Settings → Database →
   Connection string**.
3. Select the **Transaction** pooler tab (port `6543`), copy the URI, and
   swap in your real DB password for the `[YOUR-PASSWORD]` placeholder.
   Use this one — Vercel's serverless functions are IPv4-only and can't
   reach Supabase's direct connection (port `5432`, IPv6-only unless you
   pay for the IPv4 add-on). The pooler also handles the fact that every
   request may come from a fresh function instance instead of one
   long-lived process.
4. Paste that URI into `DATABASE_URL` (locally in `.env`, in production as
   a Vercel env var — see below). `settings.py` already sets
   `sslmode=require` and disables psycopg3 server-side prepared statements
   for any Postgres `DATABASE_URL`, since Supabase's pooler runs pgbouncer
   in transaction mode and prepared statements don't survive across pooled
   connections.
5. Run migrations against it once, from your machine:
   ```bash
   DATABASE_URL="<your supabase pooler URI>" python manage.py migrate
   ```

## Deploying to Vercel

Vercel auto-detects Django (via `manage.py` + `WSGI_APPLICATION`), runs
`collectstatic` for you at build time, and needs no `Procfile` or build
script. `vercel.json` in this repo only bumps the function's `maxDuration`
to 30s, since trip planning calls out to OpenRouteService.

1. Push this repo to GitHub.
2. In the Vercel dashboard: **Add New → Project**, import the repo, set
   **Root Directory** to `backend`.
3. Add environment variables (Project Settings → Environment Variables):
   `SECRET_KEY` (generate a new one, don't reuse the local dev one),
   `DEBUG=False`, `ALLOWED_HOSTS` (your `*.vercel.app` domain),
   `CSRF_TRUSTED_ORIGINS=https://<your-backend>.vercel.app`,
   `DATABASE_URL` (the Supabase pooler URI from above), `ORS_API_KEY`,
   `CORS_ALLOWED_ORIGINS` (set once the frontend is deployed — see below).
4. Deploy. Note the resulting URL (e.g. `https://eld-trip-planner-api.vercel.app`).
5. Vercel doesn't run `migrate` for you — it's already been run once
   against Supabase in step 5 above. Re-run it the same way after any
   migration-changing deploy.

## Connecting the Two Apps

Once both are deployed:
1. Copy the frontend's deployed URL (e.g. `https://eld-trip-planner.vercel.app`)
   into this backend's `CORS_ALLOWED_ORIGINS` env var on Vercel, redeploy.
2. Copy this backend's deployed URL + `/api/` into the frontend's
   `VITE_API_BASE_URL` env var on Vercel, redeploy (Vite bakes env vars in
   at build time — a redeploy is required after changing it).

See [`../frontend/README.md`](../frontend/README.md) for the frontend side
of this handoff.
