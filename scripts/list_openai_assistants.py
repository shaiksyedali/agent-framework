import asyncio
import os
import json
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("list_assistants")

async def main():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
    
    logger.info(f"Connecting to: {endpoint}")

    if api_key:
        client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
    else:
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
        client = AsyncAzureOpenAI(
            azure_ad_token_provider=token_provider,
            azure_endpoint=endpoint,
            api_version=api_version,
        )

    try:
        assistants = await client.beta.assistants.list(limit=20)
        logger.info(f"Found {len(assistants.data)} assistants.")
        for a in assistants.data:
            logger.info(f" - {a.name}: {a.id}")
            
    except Exception as e:
        logger.error(f"Error listing assistants: {e}")
    
    await client.close()

if __name__ == "__main__":
    from pathlib import Path
    load_env = Path(".env.azure")
    if load_env.exists():
        with open(load_env) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v
    asyncio.run(main())
