# AnimeAI — Backend

Semantic anime recommendation engine. Powered by narrative-level AI understanding.

## Architecture

```
pipeline/ingest.py     ← Pulls ~2000 anime from AniList GraphQL API
pipeline/enricher.py   ← Uses Claude to extract narrative schema per anime
engine/recommender.py  ← Vector search + NL query parsing + explanation generation
api/routes.py          ← FastAPI REST endpoints
db/schema.py           ← PostgreSQL + pgvector schema
```

## First-Time Setup

### Prerequisites
- Python 3.11+
- PostgreSQL 15+ with pgvector extension
- An Anthropic API key (console.anthropic.com)

### Install pgvector (Mac)
```bash
brew install pgvector
```

### Install pgvector (Ubuntu/Debian)
```bash
sudo apt install postgresql-15-pgvector
```

### Install dependencies
```bash
pip install -r requirements.txt
```

### Configure environment
```bash
cp .env.example .env
# Edit .env with your DATABASE_URL and ANTHROPIC_API_KEY
```

### Run setup
```bash
python setup.py
```

## Running the Pipeline

### Step 1: Ingest anime from AniList
```bash
# Ingest top 500 most popular anime (free, no key needed)
python -m pipeline.ingest --limit 500

# Ingest more for better coverage
python -m pipeline.ingest --limit 2000
```

### Step 2: Enrich with AI narrative schema
```bash
# Enrich 50 anime with Claude narrative extraction
# Each call uses ~300 input tokens + ~200 output tokens
python -m pipeline.enricher --batch-size 50 --show-sample

# Check cost: 50 anime ≈ $0.05–0.10 with claude-sonnet
# 500 anime ≈ $0.50–1.00
```

### Step 3: Start the API
```bash
uvicorn api.main:app --reload --port 8000
```

### Step 4: Test it
```bash
# Natural language search
curl "http://localhost:8000/api/anime/search?q=underdog+who+works+hard+to+get+stronger"

# Similarity search (21 = One Piece on AniList)
curl "http://localhost:8000/api/anime/21/similar"

# Get anime detail
curl "http://localhost:8000/api/anime/21"

# Interactive API docs
open http://localhost:8000/docs
```

## Database Schema

| Table | Purpose |
|---|---|
| `anime` | Raw metadata from AniList |
| `anime_narrative` | AI-enriched narrative dimensions (the secret sauce) |
| `anime_embedding` | pgvector embeddings for similarity search |
| `users` | User accounts |
| `user_ratings` | Likes, completions, drops |

## Important: Embeddings

The MVP uses a **placeholder embedding** (hash-based, not real). This means similarity
search won't produce good results until you swap in a real embedding model.

**To fix this (recommended for first real test):**

Option A — OpenAI (best quality, ~$0.001 per 1000 anime):
```python
# In pipeline/enricher.py, replace generate_embedding() with:
from openai import OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
response = openai_client.embeddings.create(
    input=text, model="text-embedding-3-large", dimensions=1024
)
return response.data[0].embedding
```

Option B — Free local embeddings (sentence-transformers):
```bash
pip install sentence-transformers
```
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-mpnet-base-v2')
return model.encode(text).tolist()  # 768 dims — update EMBEDDING_DIM in schema.py
```

## Cost Estimates (Claude API)

| Task | Tokens | Cost |
|---|---|---|
| Enrich 1 anime | ~500 in / ~200 out | ~$0.002 |
| Enrich 500 anime | ~250K in / ~100K out | ~$1.00 |
| One NL query parse | ~200 in / ~100 out | ~$0.001 |
| One explanation | ~300 in / ~100 out | ~$0.001 |
| 1000 recommendations/day | ~500K tokens | ~$2/day |
