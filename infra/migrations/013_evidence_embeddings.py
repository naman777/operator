"""Migration 013: provenance-preserving evidence chunks with vector embeddings."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, JSON, MetaData, String, Table

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
Table("profile_documents", metadata, Column("id", String, primary_key=True))
chunks = Table(
    "evidence_chunks",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("document_id", String, ForeignKey("profile_documents.id"), nullable=False, index=True),
    Column("text", String, nullable=False),
    Column("source_location", String, nullable=False),
    Column("skills", JSON, nullable=False),
    Column("embedding", Vector(256), nullable=False),
)


def upgrade(connection):
    chunks.create(connection, checkfirst=True)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_evidence_chunks_embedding_hnsw "
            "ON evidence_chunks USING hnsw (embedding vector_cosine_ops)"
        )
