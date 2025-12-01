from agent_framework.data.vector_store import DocumentIngestionService


def test_ingestion_chunks_and_merges_metadata():
    service = DocumentIngestionService(chunk_size=10, chunk_overlap=2)
    ids = service.ingest([
        {"text": "abc def ghi jkl", "id": "doc-1", "title": "notes"},
        "standalone doc",
    ])

    assert len(ids) > 2  # multiple chunks were created

    results = service.search("abc", top_k=5)
    assert results[0].metadata["source_id"] == "doc-1"
    assert results[0].metadata["title"] == "notes"
    assert "chunk_index" in results[0].metadata

