# Contributing to VDL2 API

Thank you for your interest in contributing. This document covers how to set up a development environment, the conventions used in this project, and the process for submitting changes.

---

## Table of contents

- [Development setup](#development-setup)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [Project conventions](#project-conventions)
- [Submitting changes](#submitting-changes)
- [Reporting issues](#reporting-issues)

---

## Development setup

You will need Python 3.11 or later. A Linux host or WSL is recommended; the systemd units and RTL-SDR device access are Linux-specific, but the Python application and tests run on any platform.

```bash
git clone https://github.com/disappointingsupernova/vdl2-api.git
cd vdl2-api

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements-dev.txt
```

You do not need a physical RTL-SDR or a running `dumpvdl2` instance to work on the application. The collector reads from a JSONL file; the test suite uses temporary files and isolated SQLite databases.

---

## Running tests

```bash
pytest -v
```

54 tests across 6 files. All must pass before a pull request will be merged.

| File | What it covers |
|---|---|
| `tests/test_parser.py` | JSON field extraction, timestamp normalisation, hashing, malformed input |
| `tests/test_database.py` | Schema creation, WAL mode, uniqueness constraints, autoincrement |
| `tests/test_collector.py` | Drain batching, checkpointing, deduplication, rotation detection, retention |
| `tests/test_api.py` | All endpoints, cursor behaviour, filters, pagination, since/until validation |
| `tests/test_auth.py` | Authentication enabled/disabled, missing/invalid key |
| `tests/test_cors.py` | CORS middleware configuration, allowed/disallowed origins |

To run a specific file:

```bash
pytest tests/test_collector.py -v
```

---

## Code style

- Follow PEP 8. Line length is not strictly enforced but keep lines readable.
- Use absolute imports (`from app.x import y`, not `from .x import y`).
- Type-annotate all function signatures. Use `from __future__ import annotations` at the top of every module.
- Do not add comments that restate what the code does. Comments should explain *why*, not *what*.
- Keep functions small and focused. If a function needs a long docstring to explain what it does, it probably needs to be split.

---

## Project conventions

### Settings

All configuration is via environment variables with the `VDL2_` prefix, defined in `app/config.py` using pydantic-settings. Add new settings there and document them in `.env.example`. Never read `os.environ` directly.

### Database

The ORM models live in `app/database.py`. Schema changes require updating the `Message` or `CollectorState` mapped classes and running `Base.metadata.create_all()`. There is no migration framework — for breaking schema changes, document a manual migration step in the PR description.

### API responses

All response shapes are defined as Pydantic models in `app/schemas.py`. Do not return raw dicts from route handlers. All timestamps must be UTC ISO 8601 strings ending in `Z`.

### The collector

The collector (`app/collector.py`) runs in a background thread. It must never crash the process — all errors must be caught, logged, and recovered from. The `drain()` function reads all available lines into a list and inserts them in a single session commit. Keep it simple and testable in isolation.

### Logging

- Operational events: `INFO`
- Security events (auth failures): `WARNING`
- Errors: `ERROR`
- High-frequency per-message detail: `DEBUG`

Do not log at `INFO` inside tight loops. The collector logs inserted/duplicate counts at `DEBUG`.

### Commit messages

Use the conventional commits format:

```
type(scope): short description

Longer explanation if needed. Wrap at 72 characters.
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`.

---

## Submitting changes

1. Fork the repository and create a branch from `main`.
2. Make your changes with focused, atomic commits.
3. Ensure `pytest -v` passes with no failures.
4. Open a pull request against `main` with a clear description of what the change does and why.

For significant changes — new endpoints, schema changes, changes to the collector reliability model — open an issue first to discuss the approach.

---

## Reporting issues

Please include:

- The output of `journalctl -u vdl2-api.service -n 100` if the service is misbehaving.
- The output of `python3 --version` and `pip show sqlalchemy fastapi`.
- A description of what you expected to happen and what actually happened.
- If relevant, a sample of the dumpvdl2 JSON that triggered the problem (redact any sensitive callsigns or registrations if needed).
