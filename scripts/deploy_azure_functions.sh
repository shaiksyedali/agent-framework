#!/bin/bash

#==============================================================================
# Azure Functions Deployment Script
#
# Deploys SQL and RAG tools as Azure Functions
#==============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

#==============================================================================
# Configuration
#==============================================================================

log_info "Loading configuration..."

# Load .env.azure
if [ -f ".env.azure" ]; then
    export $(cat .env.azure | grep -v '^#' | xargs)
    log_info "✓ Loaded .env.azure"
else
    log_error ".env.azure not found. Please create it first."
    exit 1
fi

# Required variables
REQUIRED_VARS=(
    "AZURE_SUBSCRIPTION_ID"
    "AZURE_RESOURCE_GROUP"
    "AZURE_LOCATION"
    "AZURE_PROJECT_NAME"
    "AZURE_OPENAI_ENDPOINT"
    "AZURE_OPENAI_API_KEY"
    "AZURE_OPENAI_DEPLOYMENT"
    "AZURE_EMBED_DEPLOYMENT"
    "AZURE_SEARCH_ENDPOINT"
    "AZURE_SEARCH_INDEX"
    "AZURE_SEARCH_KEY"
    "AZURE_AI_PROJECT_ENDPOINT"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        log_error "Required variable $var is not set"
        exit 1
    fi
done

log_info "✓ All required variables are set"

# Function App name (unique)
FUNCTION_APP_NAME="${AZURE_PROJECT_NAME}-functions"
STORAGE_ACCOUNT_NAME="${AZURE_PROJECT_NAME}storage"
KEY_VAULT_NAME="${AZURE_PROJECT_NAME}-kv"

log_info "Deployment configuration:"
log_info "  Subscription: $AZURE_SUBSCRIPTION_ID"
log_info "  Resource Group: $AZURE_RESOURCE_GROUP"
log_info "  Location: $AZURE_LOCATION"
log_info "  Function App: $FUNCTION_APP_NAME"
log_info "  Storage Account: $STORAGE_ACCOUNT_NAME"
log_info "  Key Vault: $KEY_VAULT_NAME"

#==============================================================================
# Prerequisites Check
#==============================================================================

log_info "Checking prerequisites..."

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    log_error "Azure CLI is not installed. Please install it first."
    exit 1
fi

# Check if logged in
if ! az account show &> /dev/null; then
    log_error "Not logged in to Azure. Please run 'az login' first."
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed."
    exit 1
fi

# Check if Azure Functions Core Tools is installed
if ! command -v func &> /dev/null; then
    log_warn "Azure Functions Core Tools is not installed."
    log_info "Install it with: npm install -g azure-functions-core-tools@4"
    log_info "Continuing without local testing capability..."
fi

log_info "✓ Prerequisites check complete"

#==============================================================================
# Set Azure subscription
#==============================================================================

log_info "Setting Azure subscription..."

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

log_info "✓ Using subscription: $(az account show --query name -o tsv)"

#==============================================================================
# Create/Verify Resource Group
#==============================================================================

log_info "Checking resource group..."

if az group show --name "$AZURE_RESOURCE_GROUP" &> /dev/null; then
    log_info "✓ Resource group exists: $AZURE_RESOURCE_GROUP"
else
    log_info "Creating resource group..."
    az group create \
        --name "$AZURE_RESOURCE_GROUP" \
        --location "$AZURE_LOCATION"
    log_info "✓ Created resource group: $AZURE_RESOURCE_GROUP"
fi

#==============================================================================
# Create Storage Account
#==============================================================================

log_info "Checking storage account..."

# Storage account name must be lowercase and alphanumeric only
STORAGE_ACCOUNT_NAME=$(echo "$STORAGE_ACCOUNT_NAME" | tr '[:upper:]' '[:lower:]' | tr -d '-')
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:0:24}"  # Max 24 chars

if az storage account show --name "$STORAGE_ACCOUNT_NAME" --resource-group "$AZURE_RESOURCE_GROUP" &> /dev/null; then
    log_info "✓ Storage account exists: $STORAGE_ACCOUNT_NAME"
else
    log_info "Creating storage account..."
    az storage account create \
        --name "$STORAGE_ACCOUNT_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --location "$AZURE_LOCATION" \
        --sku Standard_LRS \
        --allow-blob-public-access false
    log_info "✓ Created storage account: $STORAGE_ACCOUNT_NAME"
fi

#==============================================================================
# Create Function App
#==============================================================================

log_info "Checking function app..."

if az functionapp show --name "$FUNCTION_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" &> /dev/null; then
    log_info "✓ Function app exists: $FUNCTION_APP_NAME"
else
    log_info "Creating function app..."
    az functionapp create \
        --name "$FUNCTION_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --storage-account "$STORAGE_ACCOUNT_NAME" \
        --consumption-plan-location "$AZURE_LOCATION" \
        --runtime python \
        --runtime-version 3.11 \
        --functions-version 4 \
        --os-type Linux
    log_info "✓ Created function app: $FUNCTION_APP_NAME"
fi

#==============================================================================
# Configure Function App Settings
#==============================================================================

log_info "Configuring function app settings..."

az functionapp config appsettings set \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --settings \
        "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT" \
        "AZURE_OPENAI_API_KEY=$AZURE_OPENAI_API_KEY" \
        "AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT" \
        "AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION" \
        "AZURE_EMBED_DEPLOYMENT=$AZURE_EMBED_DEPLOYMENT" \
        "AZURE_EMBED_DIM=$AZURE_EMBED_DIM" \
        "AZURE_SEARCH_ENDPOINT=$AZURE_SEARCH_ENDPOINT" \
        "AZURE_SEARCH_INDEX=$AZURE_SEARCH_INDEX" \
        "AZURE_SEARCH_KEY=$AZURE_SEARCH_KEY" \
        "AZURE_AI_PROJECT_ENDPOINT=$AZURE_AI_PROJECT_ENDPOINT" \
        "SEMANTIC_CONFIG_NAME=${SEMANTIC_CONFIG_NAME:-default}" \
        "AZURE_DOC_INTELLIGENCE_ENDPOINT=${AZURE_DOC_INTELLIGENCE_ENDPOINT:-}" \
        "AZURE_DOC_INTELLIGENCE_KEY=${AZURE_DOC_INTELLIGENCE_KEY:-}" \
        "AZURE_LANGUAGE_ENDPOINT=${AZURE_LANGUAGE_ENDPOINT:-}" \
        "AZURE_LANGUAGE_KEY=${AZURE_LANGUAGE_KEY:-}" \
        "ENABLE_DOC_INTELLIGENCE=${ENABLE_DOC_INTELLIGENCE:-true}" \
        "CHUNKING_STRATEGY=${CHUNKING_STRATEGY:-paragraph}" \
        "CHUNK_SIZE_TOKENS=${CHUNK_SIZE_TOKENS:-800}" \
        "CHUNK_OVERLAP_TOKENS=${CHUNK_OVERLAP_TOKENS:-100}" \
        "ENABLE_CHUNK_SUMMARIES=${ENABLE_CHUNK_SUMMARIES:-false}" \
        "ENABLE_LLM_ENTITY_EXTRACTION=${ENABLE_LLM_ENTITY_EXTRACTION:-false}" \
        "SCM_DO_BUILD_DURING_DEPLOYMENT=true" \
        "ENABLE_ORYX_BUILD=true" \
    > /dev/null

log_info "✓ Configured function app settings"

#==============================================================================
# Enable Managed Identity (Optional)
#==============================================================================

log_info "Enabling managed identity..."

IDENTITY_OUTPUT=$(az functionapp identity assign \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --output json)

PRINCIPAL_ID=$(echo "$IDENTITY_OUTPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('principalId', ''))")

if [ -n "$PRINCIPAL_ID" ]; then
    log_info "✓ Managed identity enabled (Principal ID: $PRINCIPAL_ID)"
    
    # Assign roles
    log_info "Assigning RBAC roles..."
    
    # Construct scope
    SCOPE="/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP"
    
    # Temporarily disable exit on error for role assignments
    set +e
    
    # Contributor on Resource Group (simpler for debugging, covers most needs)
    az role assignment create \
        --assignee "$PRINCIPAL_ID" \
        --role "Contributor" \
        --scope "$SCOPE" \
        || echo "  [WARN] Failed to assign 'Contributor' role. You may need to ask an admin to do this."

    # Search Index Data Reader (specifically for Search)
    az role assignment create \
        --assignee "$PRINCIPAL_ID" \
        --role "Search Index Data Reader" \
        --scope "$SCOPE" \
        || echo "  [WARN] Failed to assign 'Search Index Data Reader' role. You may need to ask an admin to do this."

    # Search Service Contributor
    az role assignment create \
        --assignee "$PRINCIPAL_ID" \
        --role "Search Service Contributor" \
        --scope "$SCOPE" \
        || echo "  [WARN] Failed to assign 'Search Service Contributor' role. You may need to ask an admin to do this."
    
    set -e
    
else
    log_warn "Failed to get principal ID from managed identity"
fi

#==============================================================================
# Deploy Functions
#==============================================================================

log_info "Deploying Azure Functions..."

cd azure-functions

# Create virtual environment and install dependencies (for deployment package)
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt --quiet

# Start simple zip deployment strategy (most reliable for custom dependencies)
if command -v func &> /dev/null; then
    log_info "Deploying using Azure Functions Core Tools..."
    func azure functionapp publish "$FUNCTION_APP_NAME" --python
else
    # Fallback/Default to zip deployment
    log_info "Deploying using zip deployment..."
    
    # Install dependencies locally for bundling (Vendoring)
    # This ensures dependencies are present even if remote build fails
    log_info "Bundling dependencies locally..."
    rm -rf .python_packages
    mkdir -p .python_packages/lib/site-packages
    # Install dependencies compatible with Azure Functions (Linux)
    pip install \
        --target .python_packages/lib/site-packages \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version 3.11 \
        --only-binary=:all: \
        --upgrade \
        -r requirements.txt \
        --quiet

    # Create deployment package
    rm -f function_app.zip
    # Zip everything including .python_packages, excluding venv and git
    zip -r function_app.zip . -x ".venv/*" ".git/*" "*.pyc" "__pycache__/*"
    
    # Deploy
    az functionapp deployment source config-zip \
        --name "$FUNCTION_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --src function_app.zip
    
    rm function_app.zip
    # Clean up local packages to keep source clean
    rm -rf .python_packages
fi

deactivate
cd ..

log_info "✓ Functions deployed successfully"

#==============================================================================
# Get Function App URL
#==============================================================================

FUNCTION_APP_URL="https://${FUNCTION_APP_NAME}.azurewebsites.net"

log_info "Function App URL: $FUNCTION_APP_URL"

#==============================================================================
# Get Function Keys (for authentication)
#==============================================================================

log_info "Retrieving function keys..."

# Wait for function app to be ready
sleep 10

# Get host key
HOST_KEY=$(az functionapp keys list \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "functionKeys.default" -o tsv 2>/dev/null || echo "")

if [ -n "$HOST_KEY" ]; then
    log_info "✓ Function host key retrieved"
    log_info "Host Key: $HOST_KEY"
    log_info ""
    log_info "Add this to your .env.azure:"
    echo "AZURE_FUNCTIONS_URL=$FUNCTION_APP_URL"
    echo "AZURE_FUNCTIONS_KEY=$HOST_KEY"
else
    log_warn "Could not retrieve function key automatically"
    log_info "You can get it manually from the Azure Portal"
fi

#==============================================================================
# Summary
#==============================================================================

echo ""
log_info "=========================================================================="
log_info "Deployment Complete!"
log_info "=========================================================================="
log_info ""
log_info "Function App: $FUNCTION_APP_NAME"
log_info "URL: $FUNCTION_APP_URL"
log_info ""
log_info "Available endpoints:"
log_info "  - POST $FUNCTION_APP_URL/api/execute_azure_sql"
log_info "  - POST $FUNCTION_APP_URL/api/get_azure_sql_schema"
log_info "  - POST $FUNCTION_APP_URL/api/consult_rag"
log_info "  - POST $FUNCTION_APP_URL/api/get_document_summary"
log_info "  - POST $FUNCTION_APP_URL/api/graph_query"
log_info "  - POST $FUNCTION_APP_URL/api/index_document"
log_info "  - POST $FUNCTION_APP_URL/api/invoke_agent"
log_info "  - POST $FUNCTION_APP_URL/api/list_available_agents"
log_info "  - POST $FUNCTION_APP_URL/api/validate_data_source"
log_info "  - POST $FUNCTION_APP_URL/api/extract_citations"
log_info "  - POST $FUNCTION_APP_URL/api/generate_followup_questions"
log_info ""
log_info "Next steps:"
log_info "  1. Test the functions using the test script"
log_info "  2. Add AZURE_FUNCTIONS_URL and AZURE_FUNCTIONS_KEY to .env.azure"
log_info "  3. Run your agent workflows"
log_info ""
log_info "=========================================================================="
