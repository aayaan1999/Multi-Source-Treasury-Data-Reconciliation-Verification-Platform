# Deploying: Netlify (frontend) + Render (backend)

The pieces and where they live:

| Piece | Host | Config |
|---|---|---|
| Databricks pipeline | Azure (already deployed) | `databricks.yml` |
| Database | Neon (already set up) | `db/schema.sql` |
| FastAPI backend | **Render** (free web service) | `render.yaml` |
| React frontend | **Netlify** | `netlify.toml` |

**Status:** the config files parse, the backend boots with Render's exact start command, and a production build of the
frontend was checked in a browser talking to an API on a different address (login, data calls, deep-link refresh).
**Not yet done:** an actual deploy on Render or Netlify. Their pricing, free-tier limits and screens change, so check
them before relying on the free tiers.

## Before you start
* The repo is pushed to GitHub, including `render.yaml`, `netlify.toml` and this file.
* Neon has the schema (`python db/apply_schema.py`), and you have the **direct** (non-pooled) connection string.
* The Databricks pipeline has run at least once. Until it has loaded Neon, the dashboard shows "No numbers yet" (that
  is the correct empty state, not a fault).

## 1. Create the demo users in Neon (once, from your laptop)
The login needs users in the database. From the project folder, in PowerShell (use Python 3.10+):

```
cd backend
& "C:\Users\Ayan\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
$env:DEMO_USER_PASSWORD = "choose-a-password"
python seed_demo_users.py
```
You should see `Demo users ready: analyst@bankx.demo, ...`. All four users share that one password. Close the window
afterwards so the connection string doesn't linger in the session.

## 2. Backend on Render
1. https://dashboard.render.com → **New +** → **Blueprint** → connect your GitHub account and pick this repo.
2. Render reads `render.yaml` and asks for the two values it deliberately doesn't store in Git:
   * `DATABASE_URL`: the Neon connection string.
   * `CORS_ORIGINS`: type `https://placeholder.netlify.app` for now; you fix it in step 4.
   (`JWT_SECRET` is generated for you.)
3. **Apply**. Wait for the first deploy to finish (a few minutes).
4. Open `https://<your-service>.onrender.com/api/v1/live`. Expect `{"status":"alive"}`. Then `/api/v1/health` should say
   `"database": true`. Copy the service URL (no trailing slash needed) for the next step.

## 3. Frontend on Netlify
1. https://app.netlify.com → **Add new site** → **Import an existing project** → GitHub → this repo.
2. Netlify reads `netlify.toml` (base folder, build command, output folder, redirect rule), so leave the build settings
   as detected.
3. Before deploying, add an environment variable: **`VITE_API_URL`** = your Render URL, e.g.
   `https://bank-data-api.onrender.com`. (It is baked in at build time: if the backend address changes, change this and
   redeploy.)
4. **Deploy**. Optionally rename the site under Site configuration → Change site name.

## 4. Tell the backend where the frontend lives
Back in Render → your service → **Environment** → set `CORS_ORIGINS` to the exact Netlify address, e.g.
`https://your-site.netlify.app` (https, no trailing slash, no path). Save; Render redeploys.

## 5. Try it
Open the Netlify address, sign in as `analyst@bankx.demo` with the password from step 1, and the executive summary
should load.

## If something's wrong
| Symptom | Likely cause |
|---|---|
| "Can't reach the server" on the login page | `VITE_API_URL` is wrong or missing (redeploy after fixing), or the Render service is still waking up |
| Red CORS error in the browser console | `CORS_ORIGINS` doesn't match the site address exactly (`http` vs `https`, a trailing slash, or a Netlify *deploy-preview* address, which is a different origin and isn't allowed) |
| Sign-in says "Incorrect email or password" | Step 1 wasn't run against this Neon database, or the password differs |
| Dashboard says "Couldn't load" / 503 | Wrong `DATABASE_URL`, or Neon is waking up: wait a minute and try again |
| Dashboard says "No numbers yet" | The Databricks pipeline hasn't loaded Neon yet |
| A refresh on `/portfolio` gives a Netlify 404 | `netlify.toml` wasn't picked up (check the file is at the repo root and the base folder is `frontend`) |
| Render deploy fails during build | Check the build log; `PYTHON_VERSION` in `render.yaml` must be a version Render supports |

## Things to know
* **Free tiers sleep.** Render's free web service spins down when idle, and the first request afterwards can take a
  minute; Neon also suspends. Open the app a few minutes before a live demo.
* **It is public.** Anyone with the Netlify address can see the login page, and the four demo accounts share one
  password. Don't put real bank data behind it, and share the address only with people you trust, until real
  authentication exists. Never commit `DATABASE_URL`, the JWT secret or the demo password.
* **Updates:** pushing to `main` should redeploy both services automatically. The frontend and backend deploy
  independently.
* **Not covered yet:** the upload button (the backend has no upload endpoint yet), Camunda (Screen 6 needs Docker and a
  larger server than these free tiers), and row-level security.
