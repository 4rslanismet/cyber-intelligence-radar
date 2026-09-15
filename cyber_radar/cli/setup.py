"""`cyber-radar setup` - interactive first-time configuration.

Writes a working .env from .env.example, asking only for the handful of
values that can't have a safe default (database connection, Gemini API
key, and whether to enable the optional Telegram/Drive integrations).
Never overwrites an existing .env without confirmation. Validates what
it can (basic format checks) before writing - does not silently accept
an obviously-wrong value.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ENV_EXAMPLE = ".env.example"
_ENV_FILE = ".env"


def _prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _prompt_yes_no(question: str, default: bool = False) -> bool:
    default_str = "Y/n" if default else "y/N"
    answer = _prompt(f"{question} ({default_str})", "").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


def _set_env_value(lines: list[str], key: str, value: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(key)}=.*$")
    out = []
    found = False
    for line in lines:
        if pattern.match(line):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    return out


def run_setup(non_interactive: bool = False) -> int:
    if not os.path.isfile(_ENV_EXAMPLE):
        print(f"{_ENV_EXAMPLE} not found - run this from the repository root.", file=sys.stderr)
        return 1

    if os.path.isfile(_ENV_FILE):
        if non_interactive or not _prompt_yes_no(f"{_ENV_FILE} already exists. Overwrite?", default=False):
            print(f"Leaving existing {_ENV_FILE} untouched.")
            return 0

    with open(_ENV_EXAMPLE, encoding="utf-8") as f:
        lines = f.read().splitlines()

    if non_interactive:
        with open(_ENV_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Wrote {_ENV_FILE} from {_ENV_EXAMPLE} with all defaults - edit it before running the radar for real.")
        return 0

    print("Cyber Intelligence Radar setup")
    print("=" * 40)
    print("Press Enter to accept a default/skip an optional value.\n")

    db_url = _prompt(
        "PostgreSQL connection URL",
        "postgresql://cyber_radar:CHANGE_ME@localhost:5432/cyber_radar",
    )
    lines = _set_env_value(lines, "DATABASE_URL", db_url)

    gemini_key = _prompt("Gemini API key (from https://aistudio.google.com/apikey)")
    if gemini_key:
        lines = _set_env_value(lines, "GEMINI_API_KEY", gemini_key)

    keywords = _prompt("Search keywords (comma-separated)", "cybersecurity,threat intelligence")
    lines = _set_env_value(lines, "KEYWORDS", keywords)

    if _prompt_yes_no("Enable Telegram digest delivery?", default=False):
        bot_token = _prompt("Telegram bot token")
        chat_id = _prompt("Telegram chat ID")
        lines = _set_env_value(lines, "TELEGRAM_BOT_TOKEN", bot_token)
        lines = _set_env_value(lines, "TELEGRAM_CHAT_ID", chat_id)
    else:
        print("Skipping Telegram - digest will always be written locally regardless.")

    if _prompt_yes_no("Enable Google Drive archival?", default=False):
        lines = _set_env_value(lines, "GDRIVE_ENABLED", "true")
        client_id = _prompt("Google OAuth client ID")
        client_secret = _prompt("Google OAuth client secret")
        lines = _set_env_value(lines, "GDRIVE_OAUTH_CLIENT_ID", client_id)
        lines = _set_env_value(lines, "GDRIVE_OAUTH_CLIENT_SECRET", client_secret)
        print("After setup, run: python -m cyber_radar.gdrive_auth")
    else:
        print("Skipping Google Drive - files are kept locally only.")

    profile = _prompt(
        "Active research profile (see profiles/examples/ for more)", "daily_cyber"
    )
    lines = _set_env_value(lines, "ACTIVE_RESEARCH_PROFILES", profile)

    with open(_ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(_ENV_FILE, 0o600)
    except OSError:
        pass

    print(f"\nWrote {_ENV_FILE}. Next steps:")
    print("  cyber-radar doctor     # verify everything is configured correctly")
    print("  cyber-radar db init    # create the database schema")
    print("  cyber-radar demo       # see a sample digest without any live calls")
    print("  cyber-radar run        # run the radar for real")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyber-radar setup")
    parser.add_argument(
        "--non-interactive", action="store_true",
        help="Write .env.example -> .env verbatim without prompting (for CI/scripted installs)",
    )
    args = parser.parse_args(argv)
    return run_setup(non_interactive=args.non_interactive)


if __name__ == "__main__":
    sys.exit(main())
