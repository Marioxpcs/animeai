"""
api/main.py
FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000

API docs auto-generated at:
    http://localhost:8000/docs
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router

app = FastAPI(
    title="AnimeAI API",
    description="Semantic anime recommendation engine",
    version="0.1.0",
)

# Allow the Next.js frontend to call us
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
]
# Add Vercel production domain if set
if os.getenv("FRONTEND_URL"):
    allowed_origins.append(os.getenv("FRONTEND_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
