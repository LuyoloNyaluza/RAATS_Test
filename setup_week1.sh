#!/usr/bin/env bash
# =============================================================================
# RAATS Week‑1 Setup Script
# - Checks Docker, installs Ollama (if needed), creates Python venv,
#   installs requirements, downloads spaCy model.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "=== RAATS Week‑1 Setup ==="
echo "Working in: $REPO_ROOT"

# 1️⃣ Docker check
if ! command -v docker &>/dev/null; then
    echo "❌ Docker not found. Please install Docker Desktop first."
    exit 1
else
    echo "✅ Docker detected: $(docker version --format '{{.Server.Version}}')"
fi

# 2️⃣ Ollama check/install (Windows – assumes manual install)
if ! command -v ollama &>/dev/null; then
    echo "⚠️ Ollama not found in PATH."
    echo "Please install Ollama manually from https://ollama.com/download"
    echo "After installation, re‑run this script."
    exit 1
else
    echo "✅ Ollama detected: $(ollama --version)"
    # Pull a small model to verify it works
    echo "Pulling llama3 (this may take a minute)..."
    ollama run llama3 "Say hello in one word."
fi

# 3️⃣ Python virtual environment
if [[ ! -d "$REPO_ROOT/venv" ]]; then
    echo "Creating Python virtual environment..."
    python -m venv "$REPO_ROOT/venv"
else
    echo "Virtual environment already exists."
fi

# Activate for the rest of the script
source "$REPO_ROOT/venv/Scripts/activate"

# 4️⃣ Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# 5️⃣ Install requirements
if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
    echo "Installing Python packages from requirements.txt..."
    pip install -r "$REPO_ROOT/requirements.txt"
else
    echo "⚠️ requirements.txt not found!"
fi

# 6️⃣ Install spaCy English model
echo "Installing spaCy English model..."
python -m spacy download en_core_web_sm

# 7️⃣ Final reminders
echo -e "\n=== Setup Complete ==="
echo "Next steps:"
echo "  1. Activate the venv: source venv/Scripts/activate"
echo "  2. Test Ollama: ollama run llama3 \"What is the sentiment of the word 'bullish'?\""
echo "  3. Open the notebooks folder and start exploring."
echo "  4. Commit any changes and push to your repo."