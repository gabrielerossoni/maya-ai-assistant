"""Small repo-local wrapper for keeping graphify output current."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_graphify(args: list[str]) -> int:
    command = [sys.executable, "-m", "graphify", *args]
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local graphify knowledge graph.")
    subparsers = parser.add_subparsers(dest="command")

    update = subparsers.add_parser("update", help="Update graphify-out from the current project.")
    update.add_argument("extra_args", nargs=argparse.REMAINDER, help="Extra arguments passed to graphify.")

    rebuild = subparsers.add_parser("rebuild", help="Rebuild graphify-out from the current project.")
    rebuild.add_argument("extra_args", nargs=argparse.REMAINDER, help="Extra arguments passed to graphify.")

    cluster = subparsers.add_parser("cluster", help="Refresh graphify communities, report, and HTML.")
    cluster.add_argument("extra_args", nargs=argparse.REMAINDER, help="Extra arguments passed to graphify.")

    query = subparsers.add_parser("query", help="Query the existing graph.")
    query.add_argument("question", help="Question to ask graphify.")
    query.add_argument("extra_args", nargs=argparse.REMAINDER, help="Extra arguments passed to graphify.")

    raw = subparsers.add_parser("raw", help="Pass arguments directly to graphify.")
    raw.add_argument("extra_args", nargs=argparse.REMAINDER, help="Arguments passed to graphify.")

    args = parser.parse_args()
    if args.command == "update":
        return run_graphify([".", "--update", *args.extra_args])
    if args.command == "rebuild":
        return run_graphify([".", *args.extra_args])
    if args.command == "cluster":
        return run_graphify(["cluster-only", str(ROOT), *args.extra_args])
    if args.command == "query":
        return run_graphify(["query", args.question, *args.extra_args])
    if args.command == "raw":
        return run_graphify(args.extra_args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
