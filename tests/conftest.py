import sys
from pathlib import Path
import os

# ensure project root is importable as module
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Provide a default OPENROUTER_API_KEY for test env to avoid runtime errors
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
