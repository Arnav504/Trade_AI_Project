"""Write gallery/index.json and the copy the public site imports."""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _live() -> int:
    """Fetch HS corridors into a temp database and publish that gallery. Leave the files alone on failure."""
    tmp = tempfile.mkdtemp(prefix="asan-comtrade-")
    db = str(Path(tmp) / "trade.db")
    env = os.environ.copy()
    env["ASAN_DB_PATH"] = db
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch_comtrade.py"), "--corridors", "--replace"],
        env=env,
    )
    if result.returncode != 0:
        print("Comtrade returned no rows. Gallery left unchanged.", file=sys.stderr)
        return 1
    os.environ["ASAN_DB_PATH"] = db
    from analytics import load_flows
    from gallery_build import build_gallery, live_note, write_gallery
    from macro_data import fetch_macro, load_macro

    flows = load_flows()
    if not flows:
        print("Comtrade returned no rows. Gallery left unchanged.", file=sys.stderr)
        return 1
    macro_rows = fetch_macro()
    world_bank_count, imf_count = load_macro(macro_rows)
    print(f"World Bank rows: {world_bank_count}. IMF rows: {imf_count}.", file=sys.stderr)
    path = write_gallery(build_gallery(data_note=live_note(len(flows), world_bank_count, imf_count)))
    print(f"Wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Rebuild the gallery from UN Comtrade corridors")
    args = parser.parse_args()
    if args.live:
        return _live()
    # The default gallery is the seeded panel, not a local Comtrade pull.
    if not os.environ.get("ASAN_DB_PATH", "").strip():
        tmp = tempfile.mkdtemp(prefix="asan-gallery-")
        os.environ["ASAN_DB_PATH"] = str(Path(tmp) / "trade.db")
    from gallery_build import write_gallery

    path = write_gallery()
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
