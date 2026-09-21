-- Core relational schema for the arXiv dataset.
-- Papers, authors and categories are separate entities joined through link tables.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS categories (
    id   SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS authors (
    id              SERIAL PRIMARY KEY,
    full_name       TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS papers (
    id                  SERIAL PRIMARY KEY,
    arxiv_id            TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    abstract            TEXT NOT NULL DEFAULT '',
    primary_category_id INTEGER REFERENCES categories(id),
    published_at        TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    doi                 TEXT,
    journal_ref         TEXT,
    content_hash        TEXT NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    author_id       INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    author_position SMALLINT NOT NULL,
    PRIMARY KEY (paper_id, author_id)
);

CREATE TABLE IF NOT EXISTS paper_categories (
    paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (paper_id, category_id)
);

-- One vector per paper. source_hash lets the embedder detect that a paper's
-- title or abstract changed and the vector needs regenerating.
CREATE TABLE IF NOT EXISTS paper_embeddings (
    paper_id    INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    embedding   vector(384) NOT NULL,
    model       TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
