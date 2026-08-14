#!/usr/bin/env python3
"""Share the emergency_routing MongoDB database with teammates.

Single-file tool. No project imports required - only `pymongo`.

EXPORT (run this on your machine, with MongoDB running):
    python share_db.py export
    # optional:
    python share_db.py export --uri "mongodb://localhost:27017" --db emergency_routing --out emergency_routing_dump.json

IMPORT (run this on each teammate's machine, with THEIR local MongoDB running):
    python share_db.py import
    # optional:
    python share_db.py import --uri "mongodb://localhost:27017" --db emergency_routing --in emergency_routing_dump.json

How to share:
    1. Run `python share_db.py export` -> creates emergency_routing_dump.json next to this script.
    2. Send BOTH files (share_db.py and emergency_routing_dump.json) to your teammates
       over chat / email / drive / whatever you prefer.
    3. Each teammate installs pymongo and runs `python share_db.py import`.
       Start MongoDB first: `docker start mongo` (or their local MongoDB).

Details:
    - The dump is written in BSON Extended JSON (v2, relaxed), so ObjectId and
      datetime values survive the round trip exactly.
    - Import CLEARS each collection first (same behaviour as the seed scripts),
      then inserts the documents, preserving the original _id values.
    - The throwaway `connection_test` collection (used by scripts/check_db.py)
      is excluded from the export.
    - Indexes are NOT part of the dump. The backend recreates all of its
      indexes automatically on startup (app/core/database.py::create_indexes).

Dependencies:
    pip install pymongo
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import pymongo
    from bson import json_util
    from pymongo import MongoClient
except ImportError:
    sys.exit(
        "ERROR: pymongo is not installed. Install it with:\n"
        "    pip install pymongo\n"
        "Then run this script again."
    )

DEFAULT_URI = "mongodb://localhost:27017"
DEFAULT_DB = "emergency_routing"
DEFAULT_FILE = Path(__file__).resolve().parent / "emergency_routing_dump.json"
EXCLUDED_COLLECTIONS = {"connection_test"}


def _connect(uri: str) -> MongoClient:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        sys.exit(f"ERROR: cannot connect to MongoDB at {uri}\n  {exc}\n"
                 "Make sure MongoDB is running (e.g. `docker start mongo`).")
    return client


def cmd_export(args) -> None:
    client = _connect(args.uri)
    try:
        db = client[args.db]
        names = sorted(
            n for n in db.list_collection_names()
            if not n.startswith("system.") and n not in EXCLUDED_COLLECTIONS
        )

        collections = {}
        for name in names:
            docs = list(db[name].find())
            collections[name] = docs

        payload = {
            "_meta": {
                "tool": "share_db.py",
                "db": args.db,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "pymongo_version": pymongo.version,
            },
            "collections": collections,
        }

        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json_util.dumps(payload, ensure_ascii=False, indent=2))

        print(f"Exported database '{args.db}' -> {args.out}")
        total = 0
        for name in names:
            count = len(collections[name])
            total += count
            print(f"  {name:<20} {count} docs")
        print(f"Total: {total} documents across {len(names)} collections.")
        print("\nNow share BOTH files with your teammates:")
        print(f"  1. {args.out}")
        print(f"  2. {Path(__file__).resolve()}")
        print("They then run:  python share_db.py import")
    finally:
        client.close()


def cmd_import(args) -> None:
    if not Path(args.infile).is_file():
        sys.exit(f"ERROR: dump file not found: {args.infile}\n"
                 "Did you receive emergency_routing_dump.json alongside this script?")

    with open(args.infile, "r", encoding="utf-8") as fh:
        payload = json_util.loads(fh.read())

    if not isinstance(payload, dict) or "collections" not in payload:
        sys.exit("ERROR: dump file has an unexpected format (missing 'collections').")

    client = _connect(args.uri)
    try:
        db = client[args.db]

        if not args.yes:
            answer = input(
                f"This will REPLACE the current contents of database "
                f"'{args.db}' on {args.uri}. Continue? [y/N]: "
            ).strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted - no changes were made.")
                return

        collections = payload["collections"]
        total = 0
        for name, docs in collections.items():
            col = db[name]
            deleted = col.delete_many({}).deleted_count
            if docs:
                col.insert_many(docs)
            total += len(docs)
            print(f"  {name:<20} cleared {deleted:>3}, inserted {len(docs):>3} docs")

        print(f"\nDatabase '{args.db}' is ready on {args.uri}.")
        print(f"Total: {total} documents restored.")
        print("Start the backend and its indexes will be created automatically:")
        print("    uvicorn app.main:app --reload")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export/import the emergency_routing MongoDB database."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="Dump the local database to a JSON file")
    p_export.add_argument("--uri", default=DEFAULT_URI, help="MongoDB URI (default: %(default)s)")
    p_export.add_argument("--db", default=DEFAULT_DB, help="Database name (default: %(default)s)")
    p_export.add_argument("--out", type=Path, default=DEFAULT_FILE, help="Output file path")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="Load the JSON dump into the local database")
    p_import.add_argument("--uri", default=DEFAULT_URI, help="MongoDB URI (default: %(default)s)")
    p_import.add_argument("--db", default=DEFAULT_DB, help="Database name (default: %(default)s)")
    p_import.add_argument("--in", dest="infile", type=Path, default=DEFAULT_FILE, help="Input dump file")
    p_import.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    p_import.set_defaults(func=cmd_import)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
