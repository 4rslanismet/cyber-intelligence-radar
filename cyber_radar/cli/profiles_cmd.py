"""`cyber-radar profiles list` / `cyber-radar profiles validate` - inspect
and validate research profiles (see docs/PROFILES.md)."""
from __future__ import annotations

import argparse
import glob
import os
import sys


def cmd_list(_args: argparse.Namespace) -> int:
    from .. import config

    active = set(config.ACTIVE_RESEARCH_PROFILES)
    paths = sorted(glob.glob(os.path.join(config.RESEARCH_PROFILES_DIR, "*.yaml")))
    if not paths:
        print(f"No profiles found in {config.RESEARCH_PROFILES_DIR}")
        return 0
    print(f"{'ID':<25} {'MODE':<10} {'ACTIVE':<8} TITLE")
    for path in paths:
        pid = os.path.splitext(os.path.basename(path))[0]
        try:
            from ..research import profiles as research_profiles

            p = research_profiles.load_profile(path)
            print(f"{p.id:<25} {p.mode:<10} {'yes' if p.id in active else 'no':<8} {p.title}")
        except Exception as e:  # noqa: BLE001
            print(f"{pid:<25} {'?':<10} {'?':<8} (failed to load: {e})")
    return 0


def cmd_validate(_args: argparse.Namespace) -> int:
    from .. import config
    from ..research import profiles as research_profiles

    ok = True
    for pid in config.ACTIVE_RESEARCH_PROFILES:
        path = os.path.join(config.RESEARCH_PROFILES_DIR, f"{pid}.yaml")
        if not os.path.isfile(path):
            print(f"FAIL  '{pid}': not found at {path}")
            ok = False
            continue
        try:
            p = research_profiles.load_profile(path)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  '{pid}': {type(e).__name__}: {e}")
            ok = False
            continue
        if p.mode != "daily" and not p.concept_groups and not p.queries:
            print(f"WARN  '{pid}': mode='{p.mode}' but has no concept_groups/queries - will match nothing")
            continue
        print(f"PASS  '{pid}'")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyber-radar profiles")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List all profiles found in the profiles directory").set_defaults(func=cmd_list)
    sub.add_parser("validate", help="Validate the currently active profiles").set_defaults(func=cmd_validate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
