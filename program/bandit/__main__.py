"""Run with `python -m bandit` from the program directory."""

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path

from .common import SERVER_URL
from .models import UCBModel, UniformModel
from .runner import DEFAULT_DB, run_experiment, save_results
from .storage import HistoryStore, driver_lock


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return number


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main(argv=None):
    parser = argparse.ArgumentParser(description="GP3 saved-history bandit experiments (offline by default)")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Fit saved data and optionally make real pulls")
    run.add_argument("--model", choices=("uniform", "ucb"), default="uniform")
    run.add_argument("--budget", type=nonnegative, default=0, help="Maximum completed online pulls this run")
    run.add_argument("--online", action="store_true", help="Enable real requests that consume group budget")
    run.add_argument("--group", help="Assigned experiment username")
    run.add_argument("--exploration", type=float, default=2.0, help="UCB exploration coefficient")
    run.add_argument("--interval", type=float, default=0.25, help="Minimum HTTP call gap, at least 0.25 s")
    run.add_argument("--timeout", type=float, default=10.0)
    run.add_argument("--max-retries", type=nonnegative, default=2, help="Retries after an uncertain response")
    run.add_argument("--log", type=Path, help="Append-only online JSONL log path")
    run.add_argument("--server", default=SERVER_URL)
    load = commands.add_parser("import-results", help="Append actual saved response dictionaries from JSONL")
    load.add_argument("input", type=Path)
    load.add_argument("--group", required=True)
    load.add_argument("--server", default=SERVER_URL)
    export = commands.add_parser("export-results", help="Export response dictionaries to a new JSONL file")
    export.add_argument("output", type=Path)
    for command in (run, load, export):
        command.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            model = UCBModel(args.exploration) if args.model == "ucb" else UniformModel()
            password = None
            if args.online and args.budget > 0:
                if not args.group:
                    parser.error("--group is required for online mode with a positive budget")
                password = os.environ.get("GP3_PASSWORD") or getpass("Group password: ")
            try:
                result = run_experiment(model, args.budget, online=args.online, db_path=args.db,
                                        username=args.group, password=password, server_url=args.server,
                                        interval=args.interval, timeout=args.timeout,
                                        max_retries=args.max_retries, log_path=args.log)
            finally:
                password = None
        elif args.command == "import-results":
            count = save_results(read_jsonl(args.input), username=args.group,
                                 db_path=args.db, server_url=args.server)
            result = {"inserted": count, "db_path": str(args.db.resolve())}
        else:
            if not args.db.is_file():
                raise ValueError("Source database does not exist")
            with driver_lock(args.db), HistoryStore(args.db) as store:
                count = store.export_jsonl(args.output)
            result = {"exported": count, "output": str(args.output.resolve())}
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Saved results and pending request state are retained.", file=sys.stderr)
        return 130
    except Exception as error:
        # A remote RuntimeError can contain arbitrary server text; do not echo it.
        print("Operation stopped ({}). Check arguments and the local log; "
              "saved results and pending request state are retained.".format(type(error).__name__),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
