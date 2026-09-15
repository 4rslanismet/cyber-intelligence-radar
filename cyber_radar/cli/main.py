"""`cyber-radar` - top-level CLI entry point (see pyproject.toml
[project.scripts])."""
from __future__ import annotations

import argparse
import sys


def _cmd_setup(args: argparse.Namespace) -> int:
    from . import setup
    return setup.main(args.rest)


def _cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor
    return doctor.main(args.rest)


def _cmd_demo(args: argparse.Namespace) -> int:
    from . import demo
    return demo.main(args.rest)


def _cmd_db(args: argparse.Namespace) -> int:
    from . import db_cmds
    return db_cmds.main(args.rest)


def _cmd_profiles(args: argparse.Namespace) -> int:
    from . import profiles_cmd
    return profiles_cmd.main(args.rest)


def _cmd_drive(args: argparse.Namespace) -> int:
    from . import drive_cmds
    return drive_cmds.main(args.rest)


def _cmd_run(args: argparse.Namespace) -> int:
    from .. import run_pipeline
    run_pipeline.main()
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    """Render the most recent locally-saved digest (data/reports/*.md) to
    stdout - for scripting/CI use without Telegram."""
    import glob
    import os
    from .. import config

    files = sorted(glob.glob(os.path.join(config.REPORTS_DIR, "*.md")), reverse=True)
    if not files:
        print("No local digest found yet - run 'cyber-radar run' first, or 'cyber-radar demo' for a sample.", file=sys.stderr)
        return 1
    with open(files[0], encoding="utf-8") as f:
        print(f.read())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyber-radar", description="Cyber Intelligence Radar CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="Interactive first-time configuration")
    p_setup.set_defaults(func=_cmd_setup)
    p_doctor = sub.add_parser("doctor", help="Run diagnostic health checks")
    p_doctor.set_defaults(func=_cmd_doctor)
    p_demo = sub.add_parser("demo", help="Render a sample digest with fixture data (no network/DB/API keys)")
    p_demo.set_defaults(func=_cmd_demo)
    p_db = sub.add_parser("db", help="Database commands (init)")
    p_db.set_defaults(func=_cmd_db)
    p_profiles = sub.add_parser("profiles", help="Research profile commands (list, validate)")
    p_profiles.set_defaults(func=_cmd_profiles)
    p_drive = sub.add_parser("drive", help="Drive Queue commands (status, scan, run, retry, verify)")
    p_drive.set_defaults(func=_cmd_drive)
    p_run = sub.add_parser("run", help="Run the radar pipeline once (news + academic collection, analysis, digest)")
    p_run.set_defaults(func=_cmd_run)
    p_digest = sub.add_parser("digest", help="Print the most recently saved local digest to stdout")
    p_digest.set_defaults(func=_cmd_digest)

    args, rest = parser.parse_known_args(argv)
    args.rest = rest
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
