import os
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

# Using AsyncQdrantClient for non-blocking I/O
client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

async def create_client_collection(client_id: str) -> str:
    """
    Create Qdrant collection named f"client_{client_id}_faces"
    Vector size: 512, distance: Cosine
    Adds payload indexes for worker_id, person_name, and created_at.
    """
    collection_name = f"client_{client_id}_faces"
    await client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=512, distance=Distance.COSINE)
    )
    # Add payload indexes for fast filtering
    await client.create_payload_index(collection_name, field_name="worker_id", field_schema="keyword")
    await client.create_payload_index(collection_name, field_name="person_name", field_schema="keyword")
    await client.create_payload_index(collection_name, field_name="created_at", field_schema="keyword")
    return collection_name

async def search_faces(
    collection_name: str,
    embedding: list[float],
    threshold: float = 0.6,
    top_k: int = 1
) -> dict | None:
    """
    Search collection for nearest vector above threshold.
    Returns { person_name, confidence, vector_id } or None.
    """
    hits = await client.search(
        collection_name=collection_name,
        query_vector=embedding,
        limit=top_k,
        score_threshold=threshold
    )
    if hits:
        hit = hits[0]
        return {
            "person_name": hit.payload.get("person_name"),
            "confidence": round(hit.score * 100, 1),
            "vector_id": str(hit.id)
        }
    return None

async def upsert_face(
    collection_name: str,
    vector_id: str,
    embedding: list[float],
    payload: dict   # { person_name, added_by_worker, created_at }
) -> str:
    """
    Insert or update face vector in collection.
    Returns vector_id.
    """
    await client.upsert(
        collection_name=collection_name,
        points=[PointStruct(
            id=vector_id,
            vector=embedding,
            payload=payload
        )]
    )
    return vector_id

async def delete_face(collection_name: str, vector_id: str):
    """
    Remove vector from collection.
    """
    await client.delete(
        collection_name=collection_name,
        points_selector=[vector_id]
    )

async def delete_collection(collection_name: str):
    """
    Completely remove a client's collection (on client deletion).
    """
    await client.delete_collection(collection_name=collection_name)
