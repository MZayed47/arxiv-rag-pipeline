-- Indexes supporting the visualization aggregations and hybrid RAG retrieval.

CREATE INDEX IF NOT EXISTS idx_papers_published_at ON papers (published_at);
CREATE INDEX IF NOT EXISTS idx_papers_updated_at ON papers (updated_at);
CREATE INDEX IF NOT EXISTS idx_papers_primary_category ON papers (primary_category_id);

CREATE INDEX IF NOT EXISTS idx_paper_categories_category ON paper_categories (category_id);
CREATE INDEX IF NOT EXISTS idx_paper_authors_author ON paper_authors (author_id);
CREATE INDEX IF NOT EXISTS idx_authors_name_trgm ON authors USING GIN (normalized_name gin_trgm_ops);

-- Full-text search column: title weighted above abstract.
ALTER TABLE papers
    ADD COLUMN IF NOT EXISTS search_tsv tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(abstract, '')), 'B')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_papers_search_tsv ON papers USING GIN (search_tsv);

CREATE INDEX IF NOT EXISTS idx_paper_embeddings_hnsw
    ON paper_embeddings USING hnsw (embedding vector_cosine_ops);
