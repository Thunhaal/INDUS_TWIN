from pathlib import Path
import sys

# Allow this script to import baseline.py when executed directly.
BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from baseline import save_baseline


if __name__ == "__main__":
    save_baseline()