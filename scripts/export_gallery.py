"""Write gallery/index.json and the copy the public site imports."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    # The committed gallery is the seeded panel, not a local Comtrade pull.
    if not os.environ.get("ASAN_DB_PATH", "").strip():
        tmp = tempfile.mkdtemp(prefix="asan-gallery-")
        os.environ["ASAN_DB_PATH"] = str(Path(tmp) / "trade.db")
    from gallery_build import write_gallery

    path = write_gallery()
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
