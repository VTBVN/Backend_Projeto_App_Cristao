"""Opt-in real-provider check through the Flask route; not part of offline tests."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", action="append", dest="references")
    args = parser.parse_args()
    references = args.references or ["João 3:16", "Salmos 23:1"]
    failed = False
    with TemporaryDirectory(prefix="app-cristao-smoke-") as directory:
        app = create_app({"APP_ENV": "testing", "MONGODB_URI": "",
                          "CACHE_SQLITE_PATH": Path(directory) / "cache.db"})
        with app.test_client() as client:
            for reference in [*references, references[0]]:
                response = client.get("/api/bible/passages", query_string={"reference": reference})
                body = response.get_json()
                data = body.get("data", {})
                print(json.dumps({
                    "requested": reference, "status": response.status_code,
                    "reference": data.get("reference"), "translation": data.get("translation"),
                    "cached": data.get("cached"), "text_length": len(data.get("text", "")),
                    "error": body.get("error", {}).get("code"),
                }, ensure_ascii=False))
                failed |= response.status_code != 200
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
