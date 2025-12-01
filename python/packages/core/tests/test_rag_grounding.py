import ast

from agent_framework.hil_workflow import LocalRetriever


def test_local_retriever_returns_grounded_snippets():
    """Retriever should surface top snippets that contain the query text."""

    retriever = LocalRetriever(
        documents=[
            "Weather data shows sun and mild temperatures today.",
            "System design docs live in the internal wiki.",
            "Financial report: revenue grew 15% quarter over quarter.",
        ],
        top_k=2,
    )

    tool_fn = retriever.tool()
    payload = tool_fn("report")

    results = ast.literal_eval(payload)
    assert len(results) == 2
    assert all("snippet" in r for r in results)
    assert results[0]["score"] >= results[1]["score"]
    assert "report" in results[0]["snippet"].lower()
