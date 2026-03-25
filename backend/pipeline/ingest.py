"""
pipeline/ingest.py
Pulls anime metadata from the AniList GraphQL API and stores it in PostgreSQL.

Usage:
    python -m pipeline.ingest --limit 500
    python -m pipeline.ingest --limit 2000 --start-page 1

AniList API is free, no key required, rate limit: ~90 requests/min.
We fetch in pages of 50 and respect rate limits automatically.
"""

import asyncio
import time
import re
import typer
import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from sqlalchemy.orm import Session
from db.database import SessionLocal, init_db
from db.schema import Anime

console = Console()
app = typer.Typer()

ANILIST_API = "https://graphql.anilist.co"
PAGE_SIZE   = 50   # AniList max per page

# ─── GraphQL Query ────────────────────────────────────────────────────────────
ANIME_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      total
      currentPage
      lastPage
      hasNextPage
    }
    media(
      type: ANIME
      sort: POPULARITY_DESC
      format_in: [TV, MOVIE, OVA, ONA]
      episodes_greater: 4
    ) {
      id
      title {
        romaji
        english
        native
      }
      description(asHtml: false)
      episodes
      status
      season
      seasonYear
      format
      genres
      tags {
        name
        rank
        isMediaSpoiler
      }
      averageScore
      popularity
      coverImage {
        large
      }
      bannerImage
      studios(isMain: true) {
        nodes {
          name
        }
      }
      source
      relations {
        edges {
          relationType
          node {
            id
          }
        }
      }
    }
  }
}
"""


# ─── Prequel resolution ─────────────────────────────────────────────────────

PREQUEL_QUERY = """
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


async def resolve_series_root(client: httpx.AsyncClient, anime_id: int, relations: list[dict]) -> int:
    """
    Trace PREQUEL relations back to the root of a series.
    Returns the AniList ID of the first season.
    """
    # Find direct prequel from already-fetched relations
    prequel_id = None
    for edge in relations:
        if edge.get("relationType") == "PREQUEL" and edge.get("node"):
            prequel_id = edge["node"]["id"]
            break

    if not prequel_id:
        return anime_id  # This IS the root

    # Chase prequels up the chain (max 10 hops to avoid infinite loops)
    current = prequel_id
    for _ in range(10):
        try:
            resp = await client.post(
                ANILIST_API,
                json={"query": PREQUEL_QUERY, "variables": {"id": current}},
                timeout=15.0,
            )
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 90))
            if remaining < 5:
                await asyncio.sleep(60)
            resp.raise_for_status()
            media = resp.json()["data"]["Media"]
            edges = media.get("relations", {}).get("edges", [])
            found_prequel = None
            for edge in edges:
                if edge.get("relationType") == "PREQUEL" and edge.get("node", {}).get("type") == "ANIME":
                    found_prequel = edge["node"]["id"]
                    break
            if not found_prequel:
                return current  # No more prequels — this is the root
            current = found_prequel
            await asyncio.sleep(0.4)
        except Exception:
            return current  # On error, use what we have

    return current


def strip_html(text: str | None) -> str | None:
    """Remove HTML tags from AniList descriptions."""
    if not text:
        return None
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean or None


def parse_anime(raw: dict) -> dict:
    """Transform AniList API response into our Anime schema format."""
    tags = [
        {"name": t["name"], "rank": t["rank"]}
        for t in raw.get("tags", [])
        if not t.get("isMediaSpoiler", False) and t.get("rank", 0) >= 60
    ]
    studios = [
        s["name"]
        for s in raw.get("studios", {}).get("nodes", [])
    ]
    cover = raw.get("coverImage", {})
    return {
        "id":            raw["id"],
        "title_romaji":  raw["title"]["romaji"] or "Unknown",
        "title_english": raw["title"].get("english"),
        "title_native":  raw["title"].get("native"),
        "description":   strip_html(raw.get("description")),
        "episodes":      raw.get("episodes"),
        "status":        raw.get("status"),
        "season":        raw.get("season"),
        "season_year":   raw.get("seasonYear"),
        "format":        raw.get("format"),
        "genres":        raw.get("genres", []),
        "tags":          tags,
        "average_score": raw.get("averageScore"),
        "popularity":    raw.get("popularity"),
        "cover_image":   cover.get("large"),
        "banner_image":  raw.get("bannerImage"),
        "studios":       studios,
        "source":        raw.get("source"),
    }


async def fetch_page(client: httpx.AsyncClient, page: int) -> dict:
    """Fetch one page of anime from AniList GraphQL API."""
    response = await client.post(
        ANILIST_API,
        json={"query": ANIME_QUERY, "variables": {"page": page, "perPage": PAGE_SIZE}},
        timeout=30.0
    )

    # AniList rate limit headers
    remaining = int(response.headers.get("X-RateLimit-Remaining", 90))
    if remaining < 5:
        console.print("[yellow]⚠ Rate limit approaching, sleeping 60s...[/yellow]")
        await asyncio.sleep(60)

    response.raise_for_status()
    return response.json()["data"]["Page"]


def upsert_anime(db: Session, anime_data: dict) -> tuple[bool, bool]:
    """
    Insert or update an anime record.
    Returns (was_inserted, was_updated).
    """
    existing = db.query(Anime).filter(Anime.id == anime_data["id"]).first()

    if existing:
        # Update fields that may have changed (score, popularity, etc.)
        for key, val in anime_data.items():
            setattr(existing, key, val)
        db.commit()
        return False, True
    else:
        anime = Anime(**anime_data)
        db.add(anime)
        db.commit()
        return True, False


@app.command()
def run(
    limit:      int = typer.Option(500,  help="Max number of anime to ingest"),
    start_page: int = typer.Option(1,    help="AniList page to start from"),
    dry_run:    bool = typer.Option(False, help="Fetch but don't write to DB"),
):
    """
    Ingest anime from AniList into the local database.

    Fetches by popularity descending, so you always get the most
    well-known titles first — important for a useful MVP.
    """
    console.rule("[bold blue]AnimeAI — AniList Ingestion Pipeline[/bold blue]")

    if not dry_run:
        init_db()

    db = SessionLocal() if not dry_run else None

    inserted  = 0
    updated   = 0
    skipped   = 0
    total_fetched = 0
    page      = start_page

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Fetching anime (target: {limit})...", total=limit)

        async def fetch_all():
            nonlocal inserted, updated, skipped, total_fetched, page

            async with httpx.AsyncClient(headers={"Content-Type": "application/json"}) as client:
                while total_fetched < limit:
                    progress.update(task, description=f"[cyan]Fetching page {page}...")

                    page_data = None
                    for attempt in range(5):
                        try:
                            page_data = await fetch_page(client, page)
                            break
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code == 429:
                                wait = 30 * (attempt + 1)
                                console.print(f"[yellow]Rate limited on page {page}, waiting {wait}s (attempt {attempt+1}/5)...[/yellow]")
                                await asyncio.sleep(wait)
                            else:
                                console.print(f"[red]HTTP error on page {page}: {e}[/red]")
                                break
                        except Exception as e:
                            console.print(f"[red]Error on page {page}: {e}[/red]")
                            break
                    if page_data is None:
                        break

                    media_list = page_data.get("media", [])
                    if not media_list:
                        console.print("[yellow]No more anime returned from AniList.[/yellow]")
                        break

                    for raw in media_list:
                        if total_fetched >= limit:
                            break

                        parsed = parse_anime(raw)

                        # Resolve series root via prequel chain
                        relations = raw.get("relations", {}).get("edges", [])
                        root_id = await resolve_series_root(client, parsed["id"], relations)
                        parsed["series_root_id"] = root_id

                        if dry_run:
                            root_label = f" (root={root_id})" if root_id != parsed["id"] else ""
                            console.print(f"  [dim]{parsed['id']:>6}[/dim]  {parsed['title_romaji']}{root_label}")
                            total_fetched += 1
                            progress.advance(task)
                            continue

                        try:
                            was_inserted, was_updated = upsert_anime(db, parsed)
                            if was_inserted:
                                inserted += 1
                            elif was_updated:
                                updated += 1
                            total_fetched += 1
                            progress.advance(task)
                        except Exception as e:
                            console.print(f"[red]DB error for {parsed['title_romaji']}: {e}[/red]")
                            db.rollback()
                            skipped += 1

                    if not page_data.get("pageInfo", {}).get("hasNextPage"):
                        console.print("[green]Reached last page of AniList results.[/green]")
                        break

                    page += 1
                    # Be respectful — AniList allows ~90 req/min
                    await asyncio.sleep(1.5)

        asyncio.run(fetch_all())

    if db:
        db.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    console.rule("[bold green]Ingestion Complete[/bold green]")
    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column(style="bold green")
    summary.add_row("Total fetched", str(total_fetched))
    summary.add_row("Inserted (new)", str(inserted))
    summary.add_row("Updated (existing)", str(updated))
    summary.add_row("Skipped (errors)", str(skipped))
    console.print(summary)
    console.print()
    console.print("[bold]Next step:[/bold] Run [cyan]python -m pipeline.enricher[/cyan] to add narrative schema via AI.")


if __name__ == "__main__":
    app()
