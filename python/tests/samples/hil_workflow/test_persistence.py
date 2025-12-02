import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT / "packages" / "core"))

import pytest


def _install_test_stubs() -> None:
    agent_framework_module = types.ModuleType("agent_framework")

    def ai_function(fn=None, **_):  # pragma: no cover - simple decorator stub
        return fn

    agent_framework_module.ai_function = ai_function
    sys.modules["agent_framework"] = agent_framework_module

    hil_module = types.ModuleType("agent_framework.hil_workflow")

    class AzureEmbeddingRetriever:  # pragma: no cover - stub class
        def __init__(self, *_, **__):
            pass

    hil_module.AzureEmbeddingRetriever = AzureEmbeddingRetriever
    sys.modules["agent_framework.hil_workflow"] = hil_module

    openai_module = types.ModuleType("openai")

    class AzureOpenAI:  # pragma: no cover - stub class
        def __init__(self, *_, **__):
            pass

        class embeddings:  # type: ignore[valid-type]
            @staticmethod
            def create(*_, **__):  # pragma: no cover - stub method
                return None

    openai_module.AzureOpenAI = AzureOpenAI
    sys.modules["openai"] = openai_module

    pydantic_module = types.ModuleType("pydantic")

    def Field(*_, **__):  # pragma: no cover - stub function
        return None

    pydantic_module.Field = Field
    sys.modules["pydantic"] = pydantic_module


_install_test_stubs()

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


def test_duplicate_ingest_updates_document(tmp_path):
    db_path = tmp_path / "hil_workflow.sqlite"
    backend = EmbeddingBackend()
    store = Store(db_path)
    vector_store = VectorStore(store, backend=backend)

    workflow_id = "workflow-duplicate"
    document_id = "doc-dup"

    original_text = "original content"
    updated_text = "updated content"

    vector_store.ingest(
        workflow_id,
        [IngestDocument(id=document_id, text=original_text, metadata={"version": "initial"})],
    )

    expected_initial_embedding = backend.embed(original_text)
    first_doc = store.list_documents(workflow_id)[0]
    assert first_doc.content == original_text
    assert first_doc.embedding == pytest.approx(expected_initial_embedding)
    assert first_doc.metadata["version"] == "initial"

    vector_store.ingest(
        workflow_id,
        [IngestDocument(id=document_id, text=updated_text, metadata={"version": "updated"})],
    )

    expected_updated_embedding = backend.embed(updated_text)
    updated_doc = store.list_documents(workflow_id)[0]
    assert updated_doc.content == updated_text
    assert updated_doc.embedding == pytest.approx(expected_updated_embedding)
    assert updated_doc.metadata["version"] == "updated"
    assert updated_doc.metadata["source_id"] == document_id
    assert updated_doc.metadata["chunk_index"] == 0


def test_ingest_twice_updates_fields_without_error(tmp_path):
    db_path = tmp_path / "hil_workflow.sqlite"
    backend = EmbeddingBackend()
    store = Store(db_path)
    vector_store = VectorStore(store, backend=backend)

    workflow_id = "workflow-regression"
    document_id = "doc-regression"

    first_count = vector_store.ingest(
        workflow_id,
        [IngestDocument(id=document_id, text="first body", metadata={"version": 1})],
    )

    assert first_count == 1

    second_count = vector_store.ingest(
        workflow_id,
        [IngestDocument(id=document_id, text="second body", metadata={"version": 2})],
    )

    assert second_count == 1

    final_doc = store.list_documents(workflow_id)[0]
    assert final_doc.content == "second body"
    assert final_doc.embedding == pytest.approx(backend.embed("second body"))
    assert final_doc.metadata["version"] == 2
    assert final_doc.metadata["source_id"] == document_id
    assert final_doc.metadata["chunk_index"] == 0


def test_duplicate_ingest_replaces_document(tmp_path):
    db_path = tmp_path / "hil_workflow.sqlite"
    backend = EmbeddingBackend()
    store = Store(db_path)
    vector_store = VectorStore(store, backend=backend)

    workflow_id = "workflow-regression-duplicate"
    document_id = "doc-regression-duplicate"

    vector_store.ingest(
        workflow_id,
        [IngestDocument(id=document_id, text="initial body", metadata={"version": "first"})],
    )

    vector_store.ingest(
        workflow_id,
        [IngestDocument(id=document_id, text="updated body", metadata={"version": "second"})],
    )

    stored_doc = store.list_documents(workflow_id)[0]

    assert stored_doc.content == "updated body"
    assert stored_doc.embedding == pytest.approx(backend.embed("updated body"))
    assert stored_doc.metadata == {
        "version": "second",
        "source_id": document_id,
        "chunk_index": 0,
    }
