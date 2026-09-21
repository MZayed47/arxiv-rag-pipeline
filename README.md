# arXiv Ingest, Store, Visualize & RAG

A small end-to-end pipeline over the public arXiv API: ingest papers on demand,
normalize and store them in PostgreSQL, serve aggregated statistics for
charting, and answer natural-language questions about the corpus with a
retrieval-augmented pipeline backed by pgvector.

---

## Architecture

```
arXiv API  ──▶  ingestion/arxiv_client.py   paginated fetch, 1 req / 3 s, retries
                        │
                        ▼
                ingestion/preprocess.py     Atom XML → clean records, UTC dates, hashes
                        │
                        ▼
                ingestion/repository.py     upsert papers / authors / categories
                        │
                        ▼
              PostgreSQL 16 + pgvector      papers, authors, categories, link tables,
                        │                   paper_embeddings (vector 384)
             ┌──────────┴───────────┐
             ▼                      ▼
   ingestion/embedder.py    app/services/aggregations.py
   stale-vector refresh     SQL aggregations for charts
             │                      │
             ▼                      ▼
   app/services/retrieval.py   GET /api/v1/stats/*
   pgvector + full-text
   hybrid search (RRF)
             │
             ▼
   app/services/rag.py  ──▶  POST /api/v1/ask
```

### Schema

| Table | Purpose |
|---|---|
| `papers` | one row per paper: `arxiv_id` (unique), title, abstract, dates, `doi`, `journal_ref`, `content_hash`, generated `search_tsv` |
| `authors` | deduplicated authors, unique on `normalized_name` |
| `categories` | arXiv category codes |
| `paper_authors` | join table with `author_position` to preserve ordering |
| `paper_categories` | join table with an `is_primary` flag |
| `paper_embeddings` | one 384-dim vector per paper plus `model` and `source_hash` |
| `schema_migrations` | applied migration versions |

Two hashes drive incremental behaviour:

* **`content_hash`** — title, abstract, `updated`, doi, journal ref, authors and
  categories. If it matches what is already stored, the paper is left alone.
* **`source_hash`** — title + abstract only. If it no longer matches the stored
  embedding's hash (or the embedding model changed), the vector is regenerated.

That combination makes re-running ingestion safe and cheap: unchanged papers are
skipped, changed papers have their rows, links and vectors refreshed.

### Design notes

* **Hybrid retrieval.** Pure vector search misses exact terms (author names,
  dataset names, acronyms); pure keyword search misses paraphrase. Both
  candidate lists are fused with reciprocal rank fusion, weighted toward the
  vector side.
* **Honest no-match.** If the best cosine similarity is below
  `RAG_MIN_SIMILARITY` *and* nothing matched full-text search, the LLM is never
  called — the API returns `grounded: false` and says so.
* **Local embeddings.** `sentence-transformers/all-MiniLM-L6-v2` runs in-process,
  so ingestion needs no API key and no network beyond arXiv itself. Only answer
  generation requires an LLM key.
* **Sync handlers.** API handlers are plain `def` functions, so FastAPI runs them
  in its threadpool. With a synchronous connection pool this avoids mixing async
  DB code with the blocking embedding model.

---

## Quick start (Docker)

```bash
cp .env.example .env
# set GEMINI_API_KEY (or LLM_PROVIDER=openai and OPENAI_API_KEY) in .env
docker compose up --build
```

That brings up Postgres with pgvector and the API. Migrations run automatically
in the API container's entrypoint — no manual steps beyond the `.env`.

Then load the dataset (one-off container, ~3–5 minutes for 1,000 papers because
of arXiv's 3-second request pacing):

```bash
docker compose run --rm ingest
```

Check it:

```bash
curl http://localhost:5088/health
curl http://localhost:5088/api/v1/stats/summary
```

Interactive docs: <http://localhost:5088/docs>

## Local development (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set DB_HOST=localhost

docker compose up -d db       # or use your own Postgres with the vector extension
python -m app.db.migrate up
python -m ingestion.run_ingestion ingest
uvicorn app.main:app --reload --port 5088
```

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `db` / `5432` / `arxiv_db` / `postgres` / `postgres` | `DATABASE_URL` overrides all of them |
| `DB_PORT_HOST` | `5432` | host port Postgres is published on |
| `API_PORT` | `5088` | |
| `LOG_LEVEL` | `INFO` | |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | API applies pending migrations on boot |
| `ARXIV_CATEGORIES` | `cs.AI,cs.LG,cs.CL,cs.CV,cs.IR` | |
| `ARXIV_PAPERS_PER_CATEGORY` | `200` | 5 × 200 = 1,000 papers |
| `ARXIV_BATCH_SIZE` | `200` | `max_results` per request |
| `ARXIV_REQUEST_DELAY` | `3.0` | seconds between requests, per arXiv's request |
| `ARXIV_CONTACT_EMAIL` | — | goes into the User-Agent |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | |
| `EMBEDDING_DIM` | `384` | must match the `vector(n)` column in migration `0001` |
| `LLM_PROVIDER` | `gemini` | `gemini` or `openai` |
| `LLM_MODEL` | `gemini-2.5-flash` | |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | — | only needed for `/ask` |
| `RAG_TOP_K` | `5` | papers passed to the LLM |
| `RAG_MIN_SIMILARITY` | `0.25` | below this, with no keyword hit, the answer is refused |

Never commit a real `.env` — `.gitignore` excludes it.

---

## Ingestion commands

```bash
# Full run: fetch, upsert, refresh stale embeddings
python -m ingestion.run_ingestion ingest

# Narrow the run
python -m ingestion.run_ingestion ingest --categories cs.AI,cs.LG --per-category 300

# Refresh pass: sort by revision date to pick up papers that changed
python -m ingestion.run_ingestion ingest --sort-by lastUpdatedDate

# Store only, embed later
python -m ingestion.run_ingestion ingest --skip-embeddings
python -m ingestion.run_ingestion embed

# Rebuild every vector (e.g. after changing the embedding model)
python -m ingestion.run_ingestion embed --rebuild

# Wipe papers, authors, categories and embeddings for a clean import
python -m ingestion.run_ingestion reset --yes

# Row counts
python -m ingestion.run_ingestion stats
```

Inside Docker, prefix with `docker compose run --rm ingest`.

`scripts/download_arxiv_dataset.py` is a standalone snapshot tool that writes
`data/arxiv_1000.json` / `.jsonl` without touching the database — handy for
inspecting the raw feed. The database path is the CLI above.

---

## Visualization API

All figures are computed in SQL from the stored tables, never re-fetched from
arXiv.

### `GET /api/v1/stats/summary`

```bash
curl http://localhost:5088/api/v1/stats/summary
```

```json
{
  "total_papers": 1000,
  "total_authors": 5456,
  "total_categories": 63,
  "embedded_papers": 1000,
  "earliest_published": "2026-08-27T19:12:33Z",
  "latest_published": "2026-09-18T17:59:56Z"
}
```

### `GET /api/v1/stats/papers-over-time`

Query params: `granularity` (`day|month|year`, default `month`), `category`,
`start`, `end`.

```bash
curl "http://localhost:5088/api/v1/stats/papers-over-time?granularity=month&category=cs.LG"
```

```json
[
  {
    "period": "2026-08",
    "paper_count": 3
  },
  {
    "period": "2026-09",
    "paper_count": 298
  }
]
```

### `GET /api/v1/stats/top-categories?limit=10`

```json
[
  {
    "category": "cs.AI",
    "paper_count": 365,
    "primary_count": 200
  },
  {
    "category": "cs.LG",
    "paper_count": 301,
    "primary_count": 200
  },
  {
    "category": "cs.CL",
    "paper_count": 270,
    "primary_count": 200
  },
  {
    "category": "cs.CV",
    "paper_count": 218,
    "primary_count": 200
  },
  {
    "category": "cs.IR",
    "paper_count": 212,
    "primary_count": 200
  },
  {
    "category": "cs.RO",
    "paper_count": 36,
    "primary_count": 0
  },
  {
    "category": "cs.CY",
    "paper_count": 21,
    "primary_count": 0
  },
  {
    "category": "stat.ML",
    "paper_count": 20,
    "primary_count": 0
  },
  {
    "category": "cs.MA",
    "paper_count": 16,
    "primary_count": 0
  },
  {
    "category": "cs.HC",
    "paper_count": 14,
    "primary_count": 0
  }
]
```

`paper_count` includes cross-listed papers; `primary_count` counts only papers
whose primary category is that code.

### `GET /api/v1/stats/top-authors?limit=5`

```json
[
  {
    "author": "Fan Zhang",
    "paper_count": 5
  },
  {
    "author": "Yu Liu",
    "paper_count": 5
  },
  {
    "author": "Dmitrij Żatuchin",
    "paper_count": 4
  },
  {
    "author": "Min Zhang",
    "paper_count": 4
  },
  {
    "author": "Wei Li",
    "paper_count": 4
  }
]
```

### `GET /api/v1/stats/authors-per-paper`

```json
{
  "average": 5.81,
  "median": 4,
  "minimum": 1,
  "maximum": 588,
  "distribution": [
    {
      "author_count": 1,
      "paper_count": 82
    },
    {
      "author_count": 2,
      "paper_count": 131
    },
    {
      "author_count": 3,
      "paper_count": 165
    },
    {
      "author_count": 4,
      "paper_count": 170
    },
    {
      "author_count": 5,
      "paper_count": 122
    },
  ]
}
```

### `GET /api/v1/stats/category-trends?limit=2&granularity=month`

One time series per top category, ready to plot as multiple lines.

```json
[
  {
    "category": "cs.AI",
    "points": [
      {
        "period": "2026-08",
        "paper_count": 8
      },
      {
        "period": "2026-09",
        "paper_count": 357
      }
    ]
  },
  {
    "category": "cs.LG",
    "points": [
      {
        "period": "2026-08",
        "paper_count": 3
      },
      {
        "period": "2026-09",
        "paper_count": 298
      }
    ]
  }
]
```

---

## RAG API

### `POST /api/v1/ask`

```bash
curl -X POST http://localhost:5088/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What approaches are used for retrieval augmented generation?", "top_k": 5}'
```

```json
{
  "question": "What approaches are used for retrieval augmented generation?",
  "answer": "Approaches used for retrieval augmented generation include:\n\n*   **Query-adaptive frameworks** that dynamically select retriever-generator configurations, such as DRAG. This framework includes DRAG_\\text",
  "sources": [
    {
      "arxiv_id": "2609.17709",
      "title": "One Size Does Not Fit All! Dynamic Retriever and Generator Selection for RAG",
      "authors": [
        "Neeraj Anand",
        "Payel Santra",
        "Partha Basuchowdhuri",
        "Debasis Ganguly",
        "Sumit Bhatia"
      ],
      "primary_category": "cs.IR",
      "published": "2026-09-15T18:20:38Z",
      "score": 0.5051,
      "url": "https://arxiv.org/abs/2609.17709"
    },
    {
      "arxiv_id": "2609.10239",
      "title": "LiteRAG: Cost-Efficient Graph-Based Retrieval-Augmented Generation",
      "authors": [
        "Daniel Alejandro Coll Tejeda",
        "Pedro García López",
        "Daniel Barcelona-Pons"
      ],
      "primary_category": "cs.IR",
      "published": "2026-09-09T14:32:07Z",
      "score": 0.4776,
      "url": "https://arxiv.org/abs/2609.10239"
    },
    {
      "arxiv_id": "2609.11390",
      "title": "VikingRAG: Accurate and Token-efficient Retrieval-augmented Generation over Structured Documents",
      "authors": [
        "Peiyuan Gao",
        "Gaoyuan Zhang",
        "Haojie Qin",
        "Yahui Sun",
        "Qianyi Zhang",
        "Yunhao Zhang",
        "Zeyu Wang",
        "Wei Lu"
      ],
      "primary_category": "cs.IR",
      "published": "2026-09-10T11:25:59Z",
      "score": 0.5864,
      "url": "https://arxiv.org/abs/2609.11390"
    },
    {
      "arxiv_id": "2609.00638",
      "title": "It Takes Two to Match: Co-Evolving Generative Retriever with Reinforcement Learning",
      "authors": [
        "Runpeng Dai",
        "Kaili Huang",
        "Changsung Kang",
        "Ciya Liao"
      ],
      "primary_category": "cs.IR",
      "published": "2026-09-01T03:17:02Z",
      "score": 0.5435,
      "url": "https://arxiv.org/abs/2609.00638"
    },
    {
      "arxiv_id": "2609.11646",
      "title": "Your Retriever Already Knows: Distribution-Shape QPP for RAG Retrieval Sufficiency",
      "authors": [
        "Matyáš Veselý",
        "Michal Průšek",
        "Jiří Franc"
      ],
      "primary_category": "cs.IR",
      "published": "2026-09-10T14:52:16Z",
      "score": 0.5138,
      "url": "https://arxiv.org/abs/2609.11646"
    }
  ],
  "grounded": true
}
```

When nothing relevant is retrieved the LLM is not called:

```json
{
  "question": "How do I bake sourdough bread?",
  "answer": "I could not find any papers in this dataset that are relevant to your question, so I do not have grounded material to answer from. ...",
  "sources": [],
  "grounded": false
}
```

`score` is the cosine similarity of the paper's abstract embedding to the
question. `grounded` tells a client whether the answer rests on retrieved
papers.

### Errors

Every error uses the same envelope:

```json
{ "error": { "code": "http_error", "message": "Answer generation is not configured. Set an LLM API key in .env." } }
```

| Status | When |
|---|---|
| `422` | request validation failed (question too short, bad `granularity`) |
| `503` | no LLM API key configured |
| `502` | the LLM provider returned an error |
| `500` | unexpected error — logged with a stack trace, not leaked to the client |

### `GET /health`

```json
{ "status": "ok", "database": "up", "llm_configured": true }
```

---

## Tests

```bash
pytest
```

25 tests covering XML parsing and normalization, date handling, missing
`doi`/`journal_ref`, hash-based change detection, arXiv client retry/backoff and
cross-listing filters, rank fusion and the weak-match rule, and the API surface
(aggregation routes, `/ask` happy path, honest no-match, missing LLM key,
validation).

The suite runs without a database or network: DB-backed services are
monkeypatched at the service boundary.

---

## Known limitations

* **Whole-abstract embeddings.** Abstracts fit comfortably in the model's window,
  so there is no chunking. Full-text ingestion would need a chunk table.
* **Deleted papers.** arXiv does not delete papers, so ingestion has no
  tombstone handling; a paper that stops appearing in the feed simply stops
  being refreshed.
* **Author identity.** Authors are deduplicated by normalized name, so two
  different researchers sharing a name collapse into one row and initials
  ("Y. Liu" vs "Yang Liu") stay separate. Real disambiguation needs ORCID.
* **Ingestion is single-process.** 1,000 papers takes a few minutes, dominated by
  the mandated 3-second pacing.
* **No auth or rate limiting** on the API — it assumes a trusted network.
* **HNSW index on a small table.** Postgres will often prefer a sequential scan
  at this row count; the index matters as the corpus grows.

## With more time

* Re-rank the fused candidates with a cross-encoder before prompting.
* Cache question embeddings and answers for repeated queries.
* Materialized views for the aggregations, refreshed at the end of ingestion.
* A `/papers` search endpoint with filters, so the visualization UI can drill
  from a chart into the underlying rows.
* Structure-aware querying: route counting questions ("how many cs.CL papers in
  January") to SQL instead of the vector index.
* Prometheus metrics and request IDs in logs.
