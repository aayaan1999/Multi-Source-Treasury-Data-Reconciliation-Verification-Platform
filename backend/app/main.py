import asyncio
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.errors
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import get_settings
from .routers import auth, health, kpi, performance, portfolio, reconciliation, reports, scenario, workflow


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool()
    # Runs in the background so a slow/asleep Neon never delays the app answering /health.
    asyncio.get_running_loop().run_in_executor(None, db.warm_pool, 5)
    yield
    db.close_pool()


app = FastAPI(title="Bank Data Platform API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(psycopg2.errors.UndefinedTable)
@app.exception_handler(psycopg2.errors.UndefinedColumn)
async def database_needs_migration(_: Request, __: Exception):
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is missing tables or columns this screen needs. Run: "
                           "python db/apply_migration.py db/migrations/001_screens_2_to_5.sql"},
    )


@app.exception_handler(psycopg2.OperationalError)
async def database_unavailable(_: Request, __: psycopg2.OperationalError):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable - try again shortly"})


for module in (health, auth, kpi, portfolio, scenario, performance, reports, workflow, reconciliation):
    app.include_router(module.router, prefix="/api/v1")
