import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT / "packages" / "core"))

from samples.demos.hil_workflow.knowledge import EmbeddingBackend, IngestDocument, VectorStore
from samples.demos.hil_workflow.persistence import Store


def test_upsert_document_overwrites_existing(tmp_path):
    db_path = tmp_path / "hil_workflow.sqlite"
    store = Store(db_path)
    vector_store = VectorStore(store, backend=EmbeddingBackend())

    workflow_id = "workflow-1"
    document_id = "doc-123"

    first_ingest = IngestDocument(id=document_id, text="first version", metadata={"version": 1})
    first_count = vector_store.ingest(workflow_id, [first_ingest])

    assert first_count == 1
    docs_after_first = store.list_documents(workflow_id)
    assert len(docs_after_first) == 1
    assert docs_after_first[0].content == "first version"
    assert docs_after_first[0].metadata["version"] == 1
    assert docs_after_first[0].metadata["source_id"] == document_id
    assert docs_after_first[0].metadata["chunk_index"] == 0

    second_ingest = IngestDocument(id=document_id, text="updated version", metadata={"version": 2})
    second_count = vector_store.ingest(workflow_id, [second_ingest])

    assert second_count == 1
    docs_after_second = store.list_documents(workflow_id)
    assert len(docs_after_second) == 1
    assert docs_after_second[0].content == "updated version"
    assert docs_after_second[0].metadata["version"] == 2
    assert docs_after_second[0].metadata["source_id"] == document_id
    assert docs_after_second[0].metadata["chunk_index"] == 0
