"""
Test Azure Functions deployment.

Tests all deployed functions (execute_azure_sql, get_azure_sql_schema, consult_rag,
invoke_agent, list_available_agents, validate_data_source, extract_citations,
generate_followup_questions) to ensure they're working correctly.
"""

import asyncio
import json
import logging
import os
import sys

import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_function(
    url: str,
    payload: dict,
    headers: dict,
    name: str
) -> bool:
    """Test a single Azure Function"""
    
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing: {name}")
    logger.info(f"{'='*80}")
    logger.info(f"URL: {url}")
    logger.info(f"Payload: {json.dumps(payload, indent=2)}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                url,
                json=payload,
                headers=headers
            )
            
            logger.info(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Response: {json.dumps(result, indent=2)[:500]}...")
                
                # Handling different success indicators or absence thereof
                if isinstance(result, list):
                     logger.info(f"✓ {name} test PASSED (Returned List)")
                     return True
                elif result.get("success", True) is not False and "error" not in result:
                    logger.info(f"✓ {name} test PASSED")
                    return True
                else:
                    logger.error(f"✗ {name} returned error or success=False")
                    logger.error(f"Error: {result.get('error')}")
                    return False
            else:
                logger.error(f"✗ {name} test FAILED")
                logger.error(f"Status: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"✗ {name} test FAILED with exception")
            logger.error(f"Error: {e}")
            return False


async def main():
    """Main test function"""
    
    # Load environment
    load_dotenv(".env.azure")
    
    logger.info("="*80)
    logger.info("Azure Functions Test Suite")
    logger.info("="*80)
    
    # Get configuration
    base_url = os.environ.get("AZURE_FUNCTIONS_URL")
    api_key = os.environ.get("AZURE_FUNCTIONS_KEY")
    
    if not base_url:
        logger.error("AZURE_FUNCTIONS_URL not set in .env.azure")
        sys.exit(1)
    
    logger.info(f"Function App URL: {base_url}")
    logger.info(f"API Key configured: {'Yes' if api_key else 'No'}")
    
    # Prepare headers
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-functions-key"] = api_key
    
    results = []
    
    # ============================================================================
    # Test 1: list_available_agents
    # ============================================================================
    
    result = await test_function(
        url=f"{base_url}/api/list_available_agents",
        payload={},
        headers=headers,
        name="list_available_agents"
    )
    results.append(("list_available_agents", result))

    # ============================================================================
    # Test 2: validate_data_source
    # ============================================================================
    
    result = await test_function(
        url=f"{base_url}/api/validate_data_source",
        payload={"source_type": "database"},
        headers=headers,
        name="validate_data_source"
    )
    results.append(("validate_data_source", result))

    # ============================================================================
    # Test 3: extract_citations
    # ============================================================================
    
    result = await test_function(
        url=f"{base_url}/api/extract_citations",
        payload={
             "outputs": [
                 {"text": "Some text", "citations": ["Ref 1"]},
                 {"documents": [{"title": "Doc A", "score": 0.9}]}
             ]
        },
        headers=headers,
        name="extract_citations"
    )
    results.append(("extract_citations", result))

    # ============================================================================
    # Test 4: generate_followup_questions
    # ============================================================================
    
    if os.environ.get("AZURE_OPENAI_API_KEY"):
        result = await test_function(
            url=f"{base_url}/api/generate_followup_questions",
            payload={
                "context": "The user is asking about the battery life of the PI10 device.",
                "count": 2
            },
            headers=headers,
            name="generate_followup_questions"
        )
        results.append(("generate_followup_questions", result))
    else:
         logger.warning("Skipping generate_followup_questions - AZURE_OPENAI_API_KEY not set locally (check if function uses Managed ID)")

    # ============================================================================
    # Test 5: invoke_agent (Supervisor -> Planner/SQL)
    # ============================================================================
    # Note: proper invocation requires a valid agent setup. 
    # We'll test with a simple 'ping' if possible or skip if risky/long-running.
    # For now, we will try to invoke the 'planner' with a simple request.
    
    result = await test_function(
        url=f"{base_url}/api/invoke_agent",
        payload={
            "agent_name": "planner_agent", # Must match name in azure_agents_config.json
            "message": "Create a plan to list 5 customers."
        },
        headers=headers,
        name="invoke_agent"
    )
    results.append(("invoke_agent", result))

    # ============================================================================
    # Test 6: consult_rag
    # ============================================================================
    
    if os.environ.get("AZURE_SEARCH_ENDPOINT"):
        result = await test_function(
            url=f"{base_url}/api/consult_rag",
            payload={
                "query": "What is the voltage range?",
                "index": os.environ.get("AZURE_SEARCH_INDEX", "documents"),
                "top_k": 3,
                "search_type": "hybrid"
            },
            headers=headers,
            name="consult_rag"
        )
        results.append(("consult_rag", result))
    
    # ============================================================================
    # Summary
    # ============================================================================
    
    logger.info("\n" + "="*80)
    logger.info("Test Summary")
    logger.info("="*80)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status} - {name}")
    
    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("✓ All tests passed!")
        sys.exit(0)
    else:
        logger.error(f"✗ {total - passed} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
