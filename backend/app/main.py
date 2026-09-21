from contextlib import asynccontextmanager

import psycopg2
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import get_settings
from .routers import auth, health, kpi, performance, portfolio, scenario


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool()
    yield
    db.close_pool()


app = FastAPI(title="Bank Data Platform API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(psycopg2.OperationalError)
async def database_unavailable(_: Request, __: psycopg2.OperationalError):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable - try again shortly"})


for module in (health, auth, kpi, portfolio, scenario, performance):
    app.include_router(module.router, prefix="/api/v1")
