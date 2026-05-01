#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "🔧 Setting up AI Job Application Agent..."

# 1. Python venv
if [ ! -d ".venv" ]; then
    echo "  Creating Python virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 2. Dependencies
echo "  Installing Python dependencies..."
pip install -q -r requirements.txt

# 3. Playwright browser
echo "  Installing Playwright Chromium..."
playwright install chromium 2>/dev/null || echo "  (playwright install skipped — install manually if needed)"

# 4. Initialize SQLite database
echo "  Initializing database..."
python3 -c "from src.memory import get_db, init_db; db = get_db(); init_db(db); print('  Database ready.')"

# 5. Ollama models
if command -v ollama &>/dev/null; then
    echo "  Pulling Ollama models..."
    ollama pull nomic-embed-text 2>/dev/null || true
    ollama pull qwen3:8b 2>/dev/null || true
    # Build custom model
    if [ -f "Modelfile" ]; then
        echo "  Building custom job-form-analyzer model..."
        ollama create job-form-analyzer -f Modelfile 2>/dev/null || true
    fi
else
    echo "  ⚠️  Ollama not found. Install: brew install ollama"
fi

# 6. Run tests
echo "  Running tests..."
python3 -m pytest tests/ -v

echo ""
echo "✅ Setup complete!"
echo "   Run: python3 agent.py --stats"
echo "   Run: python3 agent.py --dry-run"
