#!/usr/bin/env python3
"""
setup.py
One-time setup script. Run this first.

What it does:
  1. Checks your .env is configured
  2. Creates the PostgreSQL database tables
  3. Enables pgvector extension
  4. Prints next steps

Usage:
    python setup.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

def check(label, condition, fix):
    if condition:
        print(f"  ✅  {label}")
        return True
    else:
        print(f"  ❌  {label}")
        print(f"      Fix: {fix}")
        return False


def main():
    print()
    print("━" * 55)
    print("  AnimeAI — Backend Setup")
    print("━" * 55)
    print()

    all_ok = True

    # ── Check env vars ────────────────────────────────────────
    print("Checking environment...")
    all_ok &= check(
        "DATABASE_URL is set",
        bool(os.getenv("DATABASE_URL")),
        "Copy .env.example to .env and fill in DATABASE_URL"
    )
    all_ok &= check(
        "ANTHROPIC_API_KEY is set",
        bool(os.getenv("ANTHROPIC_API_KEY")),
        "Add your Anthropic API key to .env — get one at console.anthropic.com"
    )
    print()

    if not all_ok:
        print("⚠  Fix the above issues then re-run setup.py")
        sys.exit(1)

    # ── Init database ─────────────────────────────────────────
    print("Initializing database...")
    try:
        from db.database import init_db
        init_db()
    except Exception as e:
        print(f"  ❌  Database init failed: {e}")
        print("      Make sure PostgreSQL is running and DATABASE_URL is correct.")
        sys.exit(1)
    print()

    # ── Print next steps ──────────────────────────────────────
    print("━" * 55)
    print("  Setup complete! Here's what to do next:")
    print("━" * 55)
    print()
    print("  Step 1 — Ingest anime from AniList (no API key needed):")
    print("    python -m pipeline.ingest --limit 500")
    print()
    print("  Step 2 — Enrich with AI narrative schema (uses Claude):")
    print("    python -m pipeline.enricher --batch-size 50 --show-sample")
    print()
    print("  Step 3 — Start the API server:")
    print("    uvicorn api.main:app --reload --port 8000")
    print()
    print("  Step 4 — Test a query:")
    print("    curl 'http://localhost:8000/api/anime/search?q=underdog+who+works+hard'")
    print()
    print("  API docs: http://localhost:8000/docs")
    print()


if __name__ == "__main__":
    main()
