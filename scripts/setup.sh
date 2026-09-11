#!/bin/bash
# Nexus - Setup Script
# Run from project root: bash scripts/setup.sh

set -e

echo "=== Nexus Setup ==="

# 1. Python virtual environment
echo "[1/5] Creating virtual environment..."
python -m venv .venv
source .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate

# 2. Install Python dependencies
echo "[2/5] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create .env from template if not exists
echo "[3/5] Checking .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Created .env from .env.example - fill in your API keys manually!"
else
    echo "  .env already exists, skipping."
fi

# 4. Ollama + Gemma 4
echo "[4/5] Checking Ollama + Gemma 4..."
if command -v ollama &> /dev/null; then
    echo "  Ollama found: $(ollama --version)"
    if ollama list | grep -q "gemma4"; then
        echo "  Gemma 4 model already pulled."
    else
        echo "  Pulling Gemma 4 model (this may take a while)..."
        ollama pull gemma4:e4b
    fi
else
    echo "  WARNING: Ollama not found. Install from https://ollama.com/download"
    echo "  Then run: ollama pull gemma4:e4b"
fi

# 5. Init database
echo "[5/5] Initializing database..."
python -c "from backend.storage.db import get_connection; get_connection(); print('  SQLite initialized.')"

echo ""
echo "=== Setup complete ==="
echo "Run the server: python -m backend.main"
echo "Or: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"
