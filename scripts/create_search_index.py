
import os
import asyncio
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticSearch,
    SemanticConfiguration,
    SemanticPrioritizedFields,
    SemanticField
)
from dotenv import load_dotenv

load_dotenv(".env.azure")

async def create_index():
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY") or os.getenv("AZURE_SEARCH_API_KEY")
    index_name = os.getenv("AZURE_SEARCH_INDEX", "schema-docs")

    if not endpoint or not key:
        print("Error: Missing AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_KEY")
        return

    print(f"Creating index '{index_name}' in {endpoint}...")

    credential = AzureKeyCredential(key)
    client = SearchIndexClient(endpoint=endpoint, credential=credential)

    # Define fields
    fields = [
        # Core identification
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="workflow_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="file_name", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True),  # "chunk" or "document_summary"
        
        # Content fields
        SearchableField(name="title", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="standard.lucene"),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="created_at", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="page_number", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="chunk_id", type=SearchFieldDataType.String, filterable=True),
        
        # Pre-computed metadata (NEW)
        SearchableField(name="chunk_summary", type=SearchFieldDataType.String),  # Summary of this chunk
        SearchableField(name="entities", type=SearchFieldDataType.String),  # JSON array of extracted entities
        SimpleField(name="category", type=SearchFieldDataType.String, filterable=True),  # Content category
        SimpleField(name="priority", type=SearchFieldDataType.String, filterable=True),  # Priority level if applicable
        SearchableField(name="keywords", type=SearchFieldDataType.String),  # JSON array of key terms
        
        # Document-level summary fields (for doc_type="document_summary")
        SearchableField(name="executive_summary", type=SearchFieldDataType.String),  # Full document summary
        SimpleField(name="total_chunks", type=SearchFieldDataType.Int32, filterable=True),
        SearchableField(name="key_findings", type=SearchFieldDataType.String),  # JSON array of key points
        SearchableField(name="table_of_contents", type=SearchFieldDataType.String),  # JSON structure
        
        # GraphRAG: Relationship and entity graph data
        SearchableField(name="relationships", type=SearchFieldDataType.String),  # JSON array of relationships
        SimpleField(name="entity_stats", type=SearchFieldDataType.String),  # JSON object with counts by type
        
        # Facetable fields for aggregation queries (count unique codes, filter by type, etc.)
        SearchField(
            name="entity_codes",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True  # Enables Azure faceting for counting unique values
        ),
        
        # Vector Field
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,  # text-embedding-3-small
            vector_search_profile_name="my-vector-profile"
        )
    ]

    # Vector Search Configuration
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name="my-hnsw-config",
                parameters={"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}
            )
        ],
        profiles=[
            VectorSearchProfile(
                name="my-vector-profile",
                algorithm_configuration_name="my-hnsw-config"
            )
        ]
    )

    # Semantic Search Configuration - Enhanced for better ranking
    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[
                        SemanticField(field_name="content"),
                        SemanticField(field_name="chunk_summary"),
                    ],
                    keywords_fields=[
                        SemanticField(field_name="keywords"),
                        SemanticField(field_name="entities"),
                    ]
                )
            )
        ]
    )

    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search
    )

    try:
        await client.create_or_update_index(index)
        print(f"Index '{index_name}' created/updated successfully.")
    except Exception as e:
        print(f"Error creating index: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(create_index())
