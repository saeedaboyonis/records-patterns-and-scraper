#!/bin/bash
# Script to pull Ollama model for document classification
# Usage: ./scripts/pull_ollama_model.sh [model_name]

set -e

MODEL="${1:-llama3.1:8b}"
CONTAINER_NAME="ollama"

echo "=============================================="
echo "Pulling Ollama model: $MODEL"
echo "=============================================="

# Check if docker compose is available
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed"
    exit 1
fi

# Start ollama service if not running
echo "Starting Ollama service..."
docker compose up -d ollama

# Wait for Ollama to be ready (use ollama list command, not curl)
echo "Waiting for Ollama to be ready..."
for i in {1..60}; do
    if docker exec $CONTAINER_NAME ollama list > /dev/null 2>&1; then
        echo "Ollama is ready!"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "Error: Ollama failed to start within 60 seconds"
        echo "Check logs with: docker logs $CONTAINER_NAME"
        exit 1
    fi
    echo "  Waiting... ($i/60)"
    sleep 1
done

# Pull the model
echo ""
echo "Pulling model: $MODEL (this may take several minutes on first run)..."
docker exec -it $CONTAINER_NAME ollama pull $MODEL

echo ""
echo "=============================================="
echo "Model '$MODEL' is ready!"
echo ""
echo "Run the classifier with:"
echo "  docker compose run --rm app python -m src.llm_classifier \\"
echo "    --input inputs/nc_records_assessment.jsonl \\"
echo "    --output outputs/doc_type_mapping.json"
echo "=============================================="
