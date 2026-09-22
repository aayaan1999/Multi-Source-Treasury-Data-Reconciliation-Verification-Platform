# Camunda 8 Self-Managed - local dev stack

Zeebe + Tasklist + Elasticsearch, per `specs/camunda-bpmn-process-design.md` section 2. No
Identity/Keycloak, no Optimize, no Connectors — deliberately excluded for this POC (see that spec
for why). Sourced from Camunda's official 8.7 distribution (`docker-compose-core.yaml`,
https://github.com/camunda/camunda-distributions), trimmed further to drop the `connectors`
service this project doesn't use.

**Operate is currently commented out** in `docker-compose.yaml` (not deleted — easy to re-add).
On this project's dev machine (Docker Desktop: 4 CPUs / 3.77GB RAM), all 4 JVMs (Zeebe,
Elasticsearch, Operate, Tasklist) bootstrapping at once starved each other of CPU badly enough
that Elasticsearch never reached `healthy`. Since Operate is only for process/incident debugging
during the build — not anything Screen 6 or the bridge workers call — dropping it to 3 services
was the simplest fix. Elasticsearch reached `healthy` within a couple of minutes once it wasn't
competing with Operate for CPU. Re-enable it (uncomment the block) if you need the Operate UI and
have the headroom, or bump Docker Desktop's CPU/memory allocation first.

**Every remaining service now has an explicit JVM heap cap and a `mem_limit`** (Elasticsearch
512m heap / 1g container cap, Zeebe and Tasklist 256m-512m heap / 768m container cap each — total
~2.5GB against this machine's 3.77GB Docker VM). Tasklist previously had no heap flag at all, so
its JVM was auto-sizing against the whole Docker VM's memory rather than a fair share of it - that
was the main unnecessary RAM cost, not Elasticsearch. Lower further at your own risk: Elasticsearch
below ~512m heap tends to fail its own bootstrap checks; the Zeebe/Tasklist floor is untested.

## Start it

**Bring Elasticsearch up first and let it become healthy before starting Zeebe/Tasklist** — on a
resource-constrained machine, starting everything with one `docker compose up -d` can starve
Elasticsearch of CPU during its own JVM bootstrap (see the Operate note above).

```bash
cd camunda
docker compose up -d elasticsearch
docker compose ps                    # wait for elasticsearch to show "healthy"
docker compose up -d                 # then bring up zeebe + tasklist
```

First start pulls several GB of images and can take a few minutes; `docker compose ps` shows each
service's health once it settles.

| Service | URL | Notes |
|---|---|---|
| Zeebe gateway (gRPC) | `localhost:26500` | what a Zeebe client SDK connects to (e.g. the bridge worker, `specs/camunda-bpmn-process-design.md` section 4) |
| Zeebe REST | `localhost:8088` | |
| Tasklist | http://localhost:8082 | human task UI - what Screen 6's React frontend calls via REST API |
| Elasticsearch | http://localhost:9200 | internal dependency, not used directly |

No auth is configured (`ZEEBE_AUTHENTICATION_MODE=none` in `.env`) - matches this project's
"four seeded demo users" pattern rather than standing up Identity/Keycloak for a POC.

## Stop it

```bash
docker compose down          # stops containers, keeps data (zeebe/elastic volumes)
docker compose down -v       # also wipes data - start clean next time
```

## Process, form and bridge workers

`process/transaction-review.bpmn` and `process/review-outcome-form.form` implement
`specs/camunda-bpmn-process-design.md` section 3 (hand-authored XML/JSON - open in Camunda
Modeler or web.camunda.io to check the diagram before deploying). `bridge/` has the Python side:

```bash
cd camunda/bridge
python -m venv .venv && .venv\Scripts\activate   # or source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # only needed if Zeebe isn't at localhost:26500

python deploy.py                    # deploy the BPMN + form to Zeebe (once, and after any edit)
python test_instance.py FRAUD       # manual routing test - also try COMPLIANCE, OPERATIONS
python poll_worker.py               # one pass: Postgres -> new process instances
python poll_worker.py --loop 300    # or run continuously, polling every 5 minutes
python outcome_worker.py            # long-lived: completes tasks -> writes review_outcomes
```

`poll_worker.py` needs `camunda_process_tracking` in the database
(`db/migrations/003_camunda_process_tracking.sql`, or a fresh `db/schema.sql`). Both workers read
`DATABASE_URL` the same way `db/apply_migration.py` does (env var, else `backend/.env`).

**Not yet verified against a live Zeebe/Tasklist deployment** - built and internally consistent
with the spec, but `docker compose up`, `deploy.py`, and an end-to-end poll -> Tasklist -> outcome
round trip haven't been run yet. Treat `specs/camunda-bpmn-process-design.md` section 6's
checkboxes as unchecked until that happens.

## Full docs

https://docs.camunda.io/docs/8.7/self-managed/setup/deploy/local/docker-compose/
