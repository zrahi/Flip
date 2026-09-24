import os
import sys
import tempfile
from pathlib import Path

os.environ["FLIP_HOME"] = tempfile.mkdtemp(prefix="flip-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
