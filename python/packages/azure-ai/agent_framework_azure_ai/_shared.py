# Copyright (c) Microsoft. All rights reserved.

from typing import ClassVar

from agent_framework._pydantic import AFBaseSettings


class AzureAISettings(AFBaseSettings):
    """Azure AI Project settings.

    The settings are first loaded from environment variables with the prefix 'AZURE_AI_'.
    If the environment variables are not found, the settings can be loaded from a .env file
    with the encoding 'utf-8'. If the settings are not found in the .env file, the settings
    are ignored; however, validation will fail alerting that the settings are missing.

    Keyword Args:
        project_endpoint: The Azure AI Project endpoint URL.
            Can be set via environment variable AZURE_AI_PROJECT_ENDPOINT.
        model_deployment_name: The name of the model deployment to use.
            Can be set via environment variable AZURE_AI_MODEL_DEPLOYMENT_NAME.
        env_file_path: If provided, the .env settings are read from this file path location.
        env_file_encoding: The encoding of the .env file, defaults to 'utf-8'.

    Examples:
        .. code-block:: python

            from agent_framework.azure import AzureAISettings

            # Using environment variables
            # Set AZURE_AI_PROJECT_ENDPOINT=https://your-project.cognitiveservices.azure.com
            # Set AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4
            settings = AzureAISettings()

            # Or passing parameters directly
            settings = AzureAISettings(
                project_endpoint="https://your-project.cognitiveservices.azure.com", model_deployment_name="gpt-4"
            )

            # Or loading from a .env file
            settings = AzureAISettings(env_file_path="path/to/.env")
    """

    env_prefix: ClassVar[str] = "AZURE_AI_"

    project_endpoint: str | None = None
    model_deployment_name: str | None = None


class AzureFoundrySettings(AFBaseSettings):
    """Azure AI Foundry multi-agent system settings.

    The settings are first loaded from environment variables with the prefix 'AZURE_'.
    If the environment variables are not found, the settings can be loaded from a .env file.

    Keyword Args:
        project_endpoint: Azure AI Foundry project endpoint URL.
            Can be set via environment variable AZURE_AI_PROJECT_ENDPOINT.
        model_deployment_name: Model deployment name (default: gpt-4o).
            Can be set via environment variable AZURE_AI_MODEL_DEPLOYMENT_NAME.
        supervisor_id: Supervisor agent ID.
        planner_id: Planner agent ID.
        executor_id: Executor agent ID.
        sql_agent_id: SQL agent ID.
        rag_agent_id: RAG agent ID.
        response_generator_id: Response generator agent ID.
        azure_sql_server: Azure SQL Server FQDN.
        azure_sql_database: Azure SQL Database name.
        azure_search_endpoint: Azure AI Search endpoint URL.
        azure_search_index_name: Azure AI Search index name.
        azure_keyvault_uri: Azure Key Vault URI.
        dev_tunnel_url: Development tunnel URL for local database access.
        env_file_path: Path to .env file.
        env_file_encoding: Encoding of .env file (default: utf-8).

    Examples:
        .. code-block:: python

            from agent_framework_azure_ai import AzureFoundrySettings

            # Using environment variables
            settings = AzureFoundrySettings()

            # Or loading from .env.azure file
            settings = AzureFoundrySettings(env_file_path=".env.azure")

            # Or passing parameters directly
            settings = AzureFoundrySettings(
                project_endpoint="https://your-project.api.azureml.ms",
                model_deployment_name="gpt-4o",
                supervisor_id="agent-xyz",
                azure_sql_server="myserver.database.windows.net"
            )
    """

    env_prefix: ClassVar[str] = "AZURE_"

    # Azure AI Foundry
    project_endpoint: str | None = None
    model_deployment_name: str = "gpt-4o"

    # Agent IDs (loaded from config file or env)
    supervisor_id: str | None = None
    planner_id: str | None = None
    executor_id: str | None = None
    sql_agent_id: str | None = None
    rag_agent_id: str | None = None
    response_generator_id: str | None = None

    # Azure SQL
    azure_sql_server: str | None = None
    azure_sql_database: str | None = None

    # Azure AI Search
    azure_search_endpoint: str | None = None
    azure_search_index_name: str | None = None

    # Key Vault
    azure_keyvault_uri: str | None = None

    # Local database tunnels
    dev_tunnel_url: str | None = None
