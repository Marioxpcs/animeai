"""
pipeline/backfill_series_root.py
Re-resolves series_root_id for ALL anime in the database by tracing
PREQUEL relations on AniList.

Usage:
    cd backend && python -m pipeline.backfill_series_root
"""

import asyncio
import sys
import io
import httpx
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.schema import Anime
from pipeline.ingest import resolve_series_root, ANILIST_API

# Fix Windows console encoding + force flush
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

RELATIONS_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    relations {
      edges {
        relationType
        node {
          id
          type
        }
      }
    }
  }
}
"""


async def backfill():
    db: Session = SessionLocal()
    all_anime = db.query(Anime).order_by(Anime.popularity.desc()).all()
    total = len(all_anime)
    print(f"--- Backfilling series_root_id for {total} anime ---")

    updated = 0
    unchanged = 0
    errors = 0
    processed = 0

    async with httpx.AsyncClient(headers={"Content-Type": "application/json"}) as client:
        for anime in all_anime:
            processed += 1
            title = anime.title_romaji[:50]

            try:
                # Fetch current relations from AniList
                for attempt in range(5):
                    try:
                        resp = await client.post(
                            ANILIST_API,
                            json={"query": RELATIONS_QUERY, "variables": {"id": anime.id}},
                            timeout=15.0,
                        )
                        remaining = int(resp.headers.get("X-RateLimit-Remaining", 90))
                        if remaining < 5:
                            print("  Rate limit approaching, sleeping 60s...")
                            await asyncio.sleep(60)
                        resp.raise_for_status()
                        break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:
                            wait = 30 * (attempt + 1)
                            print(f"  Rate limited, waiting {wait}s (attempt {attempt+1}/5)...")
                            await asyncio.sleep(wait)
                        else:
                            raise
                else:
                    print(f"  SKIP {title}: too many retries")
                    errors += 1
                    continue

                media = resp.json()["data"]["Media"]

                if media is None:
                    errors += 1
                    continue

                edges = media.get("relations", {}).get("edges", [])
                root_id = await resolve_series_root(client, anime.id, edges)

                if anime.series_root_id != root_id:
                    old = anime.series_root_id
                    anime.series_root_id = root_id
                    db.commit()
                    updated += 1
                    print(f"  [{processed}/{total}] UPDATED {title}: {old} -> {root_id}")
                else:
                    unchanged += 1
                    if processed % 100 == 0:
                        print(f"  [{processed}/{total}] progress checkpoint...")

            except Exception as e:
                print(f"  [{processed}/{total}] ERROR {title}: {e}")
                db.rollback()
                errors += 1

            await asyncio.sleep(1.5)

    db.close()

    # Stats
    db2 = SessionLocal()
    total_anime = db2.query(Anime).count()
    unique_series = db2.query(Anime.series_root_id).distinct().count()
    db2.close()

    print()
    print("--- Backfill Complete ---")
    print(f"  Total anime:    {total_anime}")
    print(f"  Unique series:  {unique_series}")
    print(f"  Updated:        {updated}")
    print(f"  Unchanged:      {unchanged}")
    print(f"  Errors:         {errors}")


if __name__ == "__main__":
    asyncio.run(backfill())
