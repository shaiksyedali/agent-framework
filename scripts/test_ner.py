"""
Test script to check what Azure AI Language NER returns for DTC-like content.
This helps us understand what entity types are recognized.
"""
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".env.azure")

async def test_ner():
    from azure.ai.textanalytics import TextAnalyticsClient
    from azure.core.credentials import AzureKeyCredential
    
    endpoint = os.environ.get("AZURE_LANGUAGE_ENDPOINT")
    key = os.environ.get("AZURE_LANGUAGE_KEY")
    
    if not endpoint or not key:
        print("ERROR: AZURE_LANGUAGE_ENDPOINT and AZURE_LANGUAGE_KEY must be set")
        return
    
    print(f"Using endpoint: {endpoint}")
    
    client = TextAnalyticsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )
    
    # Sample text similar to DTC error codes
    test_texts = [
        "DTC 0x89F3EE indicates CAN_B error warning. Detection condition: Normal mode.",
        "EvoBus MCM C02: No message within the determined period. Checksum error.",
        "Temperature sensor TCU failure at -30°C. Restart required.",
        "Error code E1234 in transmission control unit. ECU reset needed.",
    ]
    
    print("\n=== Testing Azure NER on DTC-like content ===\n")
    
    for text in test_texts:
        print(f"Text: {text[:60]}...")
        result = client.recognize_entities([text])
        
        for doc in result:
            if doc.is_error:
                print(f"  ERROR: {doc.error}")
            else:
                if doc.entities:
                    print(f"  Entities found:")
                    for entity in doc.entities:
                        print(f"    - {entity.text} [{entity.category}] (confidence: {entity.confidence_score:.2f})")
                else:
                    print("  No entities found!")
        print()


if __name__ == "__main__":
    asyncio.run(test_ner())
