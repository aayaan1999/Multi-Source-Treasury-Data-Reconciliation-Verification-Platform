# Camunda 8 Self-Managed - local dev stack

Zeebe + Operate + Tasklist + Elasticsearch only, per `specs/camunda-bpmn-process-design.md`
section 2. No Identity/Keycloak, no Optimize, no Connectors — deliberately excluded for this POC
(see that spec for why). Sourced from Camunda's official 8.7 distribution
(`docker-compose-core.yaml`, https://github.com/camunda/camunda-distributions), trimmed further
to drop the `connectors` service this project doesn't use.

## Start it

```bash
cd camunda
docker compose up -d
```

First start pulls several GB of images and can take a few minutes; `docker compose ps` shows each
service's health once it settles.

| Service | URL | Notes |
|---|---|---|
| Zeebe gateway (gRPC) | `localhost:26500` | what a Zeebe client SDK connects to (e.g. the bridge worker, `specs/camunda-bpmn-process-design.md` section 4) |
| Zeebe REST | `localhost:8088` | |
| Operate | http://localhost:8081 | process/incident monitoring |
| Tasklist | http://localhost:8082 | human task UI - what Screen 6's React frontend calls via REST API |
| Elasticsearch | http://localhost:9200 | internal dependency, not used directly |

No auth is configured (`ZEEBE_AUTHENTICATION_MODE=none` in `.env`) - matches this project's
"four seeded demo users" pattern rather than standing up Identity/Keycloak for a POC.

## Stop it

```bash
docker compose down          # stops containers, keeps data (zeebe/elastic volumes)
docker compose down -v       # also wipes data - start clean next time
```

## Full docs

https://docs.camunda.io/docs/8.7/self-managed/setup/deploy/local/docker-compose/
