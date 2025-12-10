#!/bin/bash
set -e

# Azure Multi-Agent Infrastructure Deployment Script
# This script deploys all required Azure resources for the multi-agent system

echo "========================================="
echo "Azure Multi-Agent Infrastructure Deploy"
echo "========================================="
echo ""

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-multiagent-rg}"
LOCATION="${LOCATION:-eastus}"
DEPLOYMENT_NAME="multiagent-deploy-$(date +%Y%m%d-%H%M%S)"

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "ERROR: Azure CLI is not installed. Please install it first:"
    echo "https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

# Check if logged in to Azure
echo "Checking Azure login status..."
az account show &> /dev/null || {
    echo "ERROR: Not logged in to Azure. Please run 'az login' first."
    exit 1
}

# Get current subscription
SUBSCRIPTION_NAME=$(az account show --query name -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "Using subscription: $SUBSCRIPTION_NAME ($SUBSCRIPTION_ID)"
echo ""

# Confirm deployment
read -p "Deploy to resource group '$RESOURCE_GROUP' in location '$LOCATION'? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# Create resource group
echo "Creating resource group: $RESOURCE_GROUP"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output table

echo ""
echo "Deploying Azure resources (this may take 10-15 minutes)..."
echo ""

# Deploy Bicep template
az deployment group create \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$(dirname "$0")/../infrastructure/azure/main.bicep" \
    --parameters location="$LOCATION" \
    --output table

# Get deployment outputs
echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""

PROJECT_ENDPOINT=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --query properties.outputs.projectEndpoint.value -o tsv)

SEARCH_ENDPOINT=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --query properties.outputs.searchEndpoint.value -o tsv)

SQL_SERVER_FQDN=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --query properties.outputs.sqlServerFqdn.value -o tsv)

SQL_DATABASE=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --query properties.outputs.sqlDatabaseName.value -o tsv)

KEYVAULT_URI=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --query properties.outputs.keyVaultUri.value -o tsv)

APPINSIGHTS_CONNECTION_STRING=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --query properties.outputs.appInsightsConnectionString.value -o tsv)

# Display configuration
echo "Configuration for .env.azure:"
echo "========================================="
echo "AZURE_AI_PROJECT_ENDPOINT=$PROJECT_ENDPOINT"
echo "AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o"
echo "AZURE_SQL_SERVER=$SQL_SERVER_FQDN"
echo "AZURE_SQL_DATABASE=$SQL_DATABASE"
echo "AZURE_SEARCH_ENDPOINT=$SEARCH_ENDPOINT"
echo "AZURE_KEYVAULT_URI=$KEYVAULT_URI"
echo "APPINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_CONNECTION_STRING"
echo "========================================="
echo ""

# Save to .env.azure
ENV_FILE="$(dirname "$0")/../.env.azure"
echo "# Azure Multi-Agent Configuration" > "$ENV_FILE"
echo "# Generated: $(date)" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"
echo "# Azure AI Foundry" >> "$ENV_FILE"
echo "AZURE_AI_PROJECT_ENDPOINT=$PROJECT_ENDPOINT" >> "$ENV_FILE"
echo "AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"
echo "# Azure SQL" >> "$ENV_FILE"
echo "AZURE_SQL_SERVER=$SQL_SERVER_FQDN" >> "$ENV_FILE"
echo "AZURE_SQL_DATABASE=$SQL_DATABASE" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"
echo "# Azure AI Search" >> "$ENV_FILE"
echo "AZURE_SEARCH_ENDPOINT=$SEARCH_ENDPOINT" >> "$ENV_FILE"
echo "AZURE_SEARCH_INDEX_NAME=schema-docs" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"
echo "# Key Vault" >> "$ENV_FILE"
echo "AZURE_KEYVAULT_URI=$KEYVAULT_URI" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"
echo "# Application Insights" >> "$ENV_FILE"
echo "APPINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_CONNECTION_STRING" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"
echo "# Local database tunnels (dev only)" >> "$ENV_FILE"
echo "# DEV_TUNNEL_URL=https://abc123.devtunnels.ms" >> "$ENV_FILE"

echo "Configuration saved to: $ENV_FILE"
echo ""

echo "Next steps:"
echo "1. Update SQL Server password in Azure Portal"
echo "2. Configure Azure AI model deployments (GPT-4o)"
echo "3. Run: python scripts/create_azure_agents.py"
echo ""
