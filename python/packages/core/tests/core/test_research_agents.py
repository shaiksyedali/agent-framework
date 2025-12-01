import pytest

from agent_framework import ReasoningAgent, ResponseGenerator, RetrievalAgent, RetrievedEvidence, Role
from agent_framework.data.vector_store import DocumentIngestionService


@pytest.mark.asyncio
async def test_retrieval_agent_returns_citations():
    ingestion = DocumentIngestionService()
    ingestion.ingest(["Cats are quiet companions."], metadata={"source": "notes", "url": "https://cats"})

    agent = RetrievalAgent(ingestion_service=ingestion, top_k=1)
    response = await agent.run("cats")

    assert len(response.messages) == 1
    assert isinstance(response.value, list)
    assert isinstance(response.value[0], RetrievedEvidence)
    assert response.value[0].metadata["source"] == "notes"
    assert response.messages[0].contents[0].annotations[0].type == "citation"


@pytest.mark.asyncio
async def test_reasoning_agent_detects_math_and_structures():
    ingestion = DocumentIngestionService()
    ingestion.ingest(["The revenue grew 12% year over year."], metadata={"source": "report"})
    retrieval = RetrievalAgent(ingestion_service=ingestion, top_k=1)
    retrieval_response = await retrieval.run("revenue growth")

    reasoning = ReasoningAgent()
    response = await reasoning.run("Compute growth", evidence=retrieval_response.value)

    assert response.value["math_required"] is True
    assert "12%" in response.value["summary"]
    assert response.messages[0].additional_properties["analysis"]["citations"]


@pytest.mark.asyncio
async def test_response_generator_formats_and_tracks_history():
    generator = ResponseGenerator()
    response = await generator.run(
        "Summarize", findings={"summary": "Key insights", "math_required": False, "citations": []}
    )

    assert response.messages[0].role == Role.ASSISTANT
    assert "Key insights" in response.messages[0].text
    assert response.value["history"][0] == response.messages[0]

