#!/bin/bash

#==============================================================================
# Start Azure Agentic Workflow UI
#==============================================================================

set -e

echo "========================================="
echo "Azure Agentic Workflow UI"
echo "========================================="

# Navigate to UI directory
cd ui/hil-workflow

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

echo ""
echo "Starting UI dev server..."
echo "  URL: http://localhost:3000"
echo ""

# Start Next.js dev server
npm run dev
