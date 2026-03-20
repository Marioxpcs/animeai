"""
api/main.py
FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000

API docs auto-generated at:
    http://localhost:8000/docs
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AnimeAI API",
    description="Semantic anime recommendation engine",
    version="0.1.0",
)

# Allow the Next.js frontend to call us
allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else [
    "https://animeai-tawny.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
]

# Also allow all Vercel preview deployments
allow_origin_regex = r"https://animeai.*\.vercel\.app"

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
