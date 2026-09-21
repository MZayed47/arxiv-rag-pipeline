"""Small helpers shared across the application."""


def to_pgvector(vector: list[float]) -> str:
    """Render a Python float list in pgvector's text input format."""
    return "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"


def chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]
