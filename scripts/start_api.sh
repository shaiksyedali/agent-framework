#!/bin/bash

#==============================================================================
# Start Azure Agentic Workflow API
#
# Usage:
#   ./scripts/start_api.sh           # Normal start (checks deps, skips if present)
#   ./scripts/start_api.sh --prod    # Production mode (no reload)
#   ./scripts/start_api.sh --install # Force reinstall dependencies
#==============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_step() { echo -e "${BLUE}→${NC} $1"; }

# Parse arguments
PROD_MODE=false
FORCE_INSTALL=false
PORT=${API_PORT:-8000}
HOST=${API_HOST:-0.0.0.0}

for arg in "$@"; do
    case $arg in
        --prod|--production)
            PROD_MODE=true
            ;;
        --install|--reinstall)
            FORCE_INSTALL=true
            ;;
        --port=*)
            PORT="${arg#*=}"
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --prod, --production  Run in production mode (no auto-reload)"
            echo "  --install             Force reinstall all dependencies"
            echo "  --port=PORT           Override port (default: 8000)"
            echo "  -h, --help            Show this help message"
            exit 0
            ;;
    esac
done

echo ""
echo "========================================="
echo "  Azure Agentic Workflow API"
echo "========================================="
echo ""

# Ensure we're in the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Load environment variables
if [ -f ".env.azure" ]; then
    set -a
    source .env.azure
    set +a
    log_info "Loaded .env.azure"
else
    log_warn "Warning: .env.azure not found"
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    log_info "Activated virtual environment"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    log_info "Activated virtual environment (.venv)"
else
    log_error "Error: Virtual environment not found"
    echo "  Run: python3 -m venv venv && source venv/bin/activate"
    exit 1
fi

# Check/install dependencies (only if missing or forced)
check_and_install() {
    local package=$1
    local import_name=${2:-$1}
    local install_cmd=$3
    
    if [ "$FORCE_INSTALL" = true ] || ! python -c "import $import_name" 2>/dev/null; then
        log_step "Installing $package..."
        eval "$install_cmd"
        return 0
    fi
    return 1
}

INSTALLED_SOMETHING=false

# Check FastAPI (core API dependency)
if [ "$FORCE_INSTALL" = true ] || ! python -c "import fastapi" 2>/dev/null; then
    log_step "Installing API requirements..."
    pip install -q -r python/packages/api/requirements.txt
    INSTALLED_SOMETHING=true
else
    log_info "API dependencies already installed"
fi

# Check agent framework packages (only install if missing)
if [ "$FORCE_INSTALL" = true ] || ! python -c "import agent_framework" 2>/dev/null; then
    log_step "Installing agent_framework..."
    pip install -q -e python/packages/core 2>/dev/null || true
    INSTALLED_SOMETHING=true
fi

if [ "$FORCE_INSTALL" = true ] || ! python -c "import agent_framework_azure" 2>/dev/null; then
    pip install -q -e python/packages/azure-ai 2>/dev/null || true
    INSTALLED_SOMETHING=true
fi

if [ "$INSTALLED_SOMETHING" = false ]; then
    log_info "All dependencies already installed"
fi

# Create data directory
mkdir -p data

# Show configuration
echo ""
echo "Configuration:"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Mode: $([ "$PROD_MODE" = true ] && echo "Production" || echo "Development")"
echo "  Docs: http://127.0.0.1:$PORT/docs"
echo ""

# Build uvicorn command
if [ "$PROD_MODE" = true ]; then
    log_step "Starting API server (production)..."
    cd python/packages/api/src
    exec python -m uvicorn api.main:app --host $HOST --port $PORT --workers 4
else
    log_step "Starting API server (dev with auto-reload)..."
    cd python/packages/api/src
    exec python -m uvicorn api.main:app --host $HOST --port $PORT --reload
fi
