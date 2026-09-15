# Installation

## Prerequisites

- **Python 3.11+**
- **PostgreSQL 14+** with the [pgvector](https://github.com/pgvector/pgvector)
  extension installed (used for an optional embedding column; the core
  pipeline works without ever populating it)
- A free **Gemini API key** from https://aistudio.google.com/apikey

## 1. Create a database and role

`cyber-radar db init` creates the *schema* (tables) but not the database
or role itself — that one-time step needs a PostgreSQL superuser and is
intentionally not automated (a public installer silently running
superuser SQL is a bigger footgun than one manual step):

```bash
sudo -u postgres psql -c "CREATE ROLE cyber_radar WITH LOGIN PASSWORD 'change-me' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE cyber_radar OWNER cyber_radar;"
sudo -u postgres psql -d cyber_radar -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

(If your role doesn't have `CREATEDB`/enough privilege to create the
`vector` extension, ask a superuser to run that last line for you.)

## 2. Clone and install

```bash
git clone <this-repo-url> cyber-intelligence-radar
cd cyber-intelligence-radar
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `cyber-radar` command (see `pyproject.toml`
`[project.scripts]`) and all required dependencies.

## 3. Configure

```bash
cyber-radar setup
```

This prompts for the database URL, your Gemini API key, search
keywords, and whether to enable the optional Telegram/Drive
integrations, then writes `.env` (mode `0600`). Run it non-interactively
in CI/scripted installs with `cyber-radar setup --non-interactive`
(copies `.env.example` verbatim — edit the result before using it for
real).

You can also copy and edit `.env.example` by hand — see
[CONFIGURATION.md](CONFIGURATION.md) for every setting.

## 4. Verify

```bash
cyber-radar doctor
```

Checks Python version, dependencies, database connectivity/schema,
directory permissions, disk space, LLM configuration, source
reachability, and profile validity. Every check prints `PASS`, `WARN`,
or `FAIL` and never prints a secret value.

## 5. Initialize the database schema

```bash
cyber-radar db init
```

Safe to re-run — uses `CREATE TABLE IF NOT EXISTS` throughout.

## 6. Try it without any live calls

```bash
cyber-radar demo
```

Renders a complete sample digest from fixture data — no API key,
network, or database required. Good for confirming your installation
works before spending any LLM quota.

## 7. Run for real

```bash
cyber-radar run
```

See [QUICKSTART.md](QUICKSTART.md) for what happens next, and
[DEPLOYMENT.md](DEPLOYMENT.md) for running this on a schedule.
