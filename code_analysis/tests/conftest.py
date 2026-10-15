import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]       # 저장소 폴더
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
