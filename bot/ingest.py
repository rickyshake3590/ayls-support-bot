"""Rebuild the Chroma index from content chunks. Run: python -m bot.ingest

The collection is dropped and recreated on every run, so the index always
matches the content folder it was built from.
"""

import sys

import chromadb
from chromadb.errors import NotFoundError
from fastembed import TextEmbedding

from . import config
from .content_loader import Chunk, load_chunks

COLLECTION = "summit"


def build_index(chunks: list[Chunk]) -> int:
    client = chromadb.PersistentClient(path=config.INDEX_DIR)
    try:
        client.delete_collection(COLLECTION)
    except NotFoundError:
        pass
    collection = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    embedder = TextEmbedding(config.EMBED_MODEL)
    texts = [c["text"] for c in chunks]
    embeddings = [vec.tolist() for vec in embedder.embed(texts)]

    collection.add(
        ids=[c["id"] for c in chunks],
        documents=texts,
        metadatas=[c["meta"] for c in chunks],
        embeddings=embeddings,
    )
    return collection.count()


def main() -> int:
    chunks = load_chunks()
    if not chunks:
        print("no chunks found in content folder", file=sys.stderr)
        return 1
    count = build_index(chunks)
    print(f"indexed {count} chunks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
