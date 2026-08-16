# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [1.0.1] — 2026-08-16

### Fixed

- `install.sh`: pip cache failure on system users with no home directory.
  `vdl2` is created with `--no-create-home`; pip tried to write to
  `/home/vdl2/.cache` which does not exist. Fixed by running pip as root
  with `HOME` set to the install directory and `--no-cache-dir`.
- `install.sh`: venv creation used `sudo -u vdl2` which fails for the same
  reason. Now creates the venv as root then `chown`s it to `vdl2`.
- `install.sh` / `update.sh`: `git` operations failed with a "dubious
  ownership" error (Git 2.35.2+) when root operates in a directory owned
  by `vdl2`. Fixed by running `git config --global --add safe.directory`
  before any git operation.
- `install.sh` / `update.sh`: `git pull` and `pip install` ran with
  `sudo -u vdl2` which fails for the no-home-directory reason above.
  Both now run as root.
- `install.sh` / `update.sh`: `--quiet` removed from pip calls. On
  Python 3.14 where no wheel exists, pip silently attempted a multi-minute
  Rust compilation with no output, appearing to hang.
- `install.sh`: Python 3.14 was a 5-second warning that let the install
  proceed and fail deep inside a Rust build. Changed to a hard failure
  with a clear error message. `pydantic-core` uses PyO3 0.24.1 which has
  a hard maximum of Python 3.13.
- `install.sh`: Error message is now distro-aware. Ubuntu 26.04 ships
  Python 3.14 as the system default and does not have `python3.12` in
  its standard repos. Ubuntu users are directed to the deadsnakes PPA;
  Raspberry Pi OS / Debian users get the standard `apt install` command.
- `install.sh`: Added `PYTHON` environment variable override so operators
  can specify a non-default interpreter without editing the script:
  `sudo bash -c 'PYTHON=python3.12 bash /opt/vdl2-api/scripts/install.sh'`.
  All `python3` calls in the script body use `${PYTHON}`.
- `install.sh` / `update.sh`: `sudo -E` replaced with `sudo bash -c '...'`
  throughout. Ubuntu's sudo configuration disables `-E` entirely, so
  environment variables must be passed inline to the bash subprocess.

---

## [1.1.0] — 2026-08-16

### Added

- `scripts/install.sh` — idempotent installation script. Checks all system
  dependencies (python3 ≥ 3.11, pip3, git, rsync, dumpvdl2, python3-venv),
  creates the `vdl2` system user and `/var/lib/vdl2` data directory, copies
  application files, creates the virtual environment, and enables systemd units.
- `scripts/update.sh` — update script. Stops the service, backs up `.env` and
  the database, runs `git pull --ff-only`, updates Python dependencies,
  reinstalls changed systemd units, restarts the service, and polls the health
  endpoint to confirm it came back up. Keeps the 5 most recent backups.
- Graceful shutdown via `threading.Event` stop signal. The collector thread is
  signalled on uvicorn shutdown and joined with a 10-second timeout.
- Comprehensive structured logging across all modules. Startup banner logs
  host, port, database path, spool path, retention period, auth state, and
  CORS origins. Auth failures logged at WARNING. DB errors in health check
  logged at ERROR.
- `tests/test_cors.py` — 3 tests verifying CORS middleware is applied correctly
  after the `_create_app()` refactor.
- `tests/conftest.py` — documents test isolation approach and the `lru_cache`
  gap, with the `cache_clear()` alternative as a commented-out reference.

### Changed

- `drain()` now reads all available lines into a batch and inserts them in a
  single `session.commit()` rather than one commit per line. Significantly
  reduces SD card writes during catch-up after an outage.
- `since` and `until` query parameters on `GET /api/v1/messages` changed from
  `str` to `datetime`. FastAPI now validates them and returns 422 for malformed
  input rather than silently producing wrong results.
- `_create_app()` defers `get_settings()` out of module scope, fixing a test
  isolation issue where importing `app.main` before patching would poison the
  settings cache.
- `import time` moved from inside the `_cleanup` closure to the top of `main.py`.

### Fixed

- `_factories` dict in `database.py` is now protected by a `threading.Lock`,
  preventing a race condition between the collector thread and the FastAPI event
  loop at startup.
- `purge_old_messages()` now computes the retention cutoff in Python and passes
  it as a bound parameter, rather than interpolating an integer into a SQL
  function argument.
- `OSError` on spool `open()` is now caught and logged; the collector sleeps
  and retries rather than spinning at full CPU.
- `has_more` in `GET /api/v1/aircraft/{icao}/messages` was hardcoded `False`;
  now correctly detects overflow using the fetch-one-extra pattern.
- Redundant `init_db()` call removed from `run_collector()`.
- Unused `VDL2_STATE` setting removed from `config.py` and `.env.example`.
- `aiofiles` and `watchdog` removed from `requirements.txt` (unused).
- `pytest`, `pytest-asyncio`, and `httpx` moved to `requirements-dev.txt`.
- systemd units hardened: `dumpvdl2.service` gains `ProtectSystem=strict`,
  `ProtectHome=true`, `PrivateTmp=true`; `vdl2-api.service` gains
  `ProtectHome=true` and `After=dumpvdl2.service Wants=dumpvdl2.service`.
- `_make_hash()` simplified to `sha256(raw_json)` — the prefix fields were
  redundant since `raw_json` contains them.
- All relative imports (`from .x`) replaced with absolute imports (`from app.x`).
- SQLAlchemy Core replaced with SQLAlchemy ORM (`DeclarativeBase`, `Mapped`,
  `mapped_column`, `Session`).

---

## [1.0.0] — 2026-08-16

### Added

- Initial release.
- `dumpvdl2` JSONL spool collector with byte-offset checkpointing and hourly
  file rotation detection.
- SQLite persistence via SQLAlchemy ORM (`Message`, `CollectorState` mapped
  classes). WAL mode with `synchronous=NORMAL`.
- SHA-256 `message_hash` deduplication via `INSERT OR IGNORE`.
- 30-day configurable message retention with background cleanup thread.
- FastAPI REST API with cursor-based polling (`after_id`).
- `GET /api/v1/messages` — paginated message list with `after_id`, `limit`,
  `since`, `until`, `icao`, `frequency` filters.
- `GET /api/v1/messages/latest` — newest N messages.
- `GET /api/v1/aircraft` — aircraft observed within a configurable time window.
- `GET /api/v1/aircraft/{icao}/messages` — messages for a specific aircraft.
- `GET /api/v1/health` — service and database health check.
- `GET /api/v1/stats` — message counts by time window and frequency.
- Optional `X-API-Key` authentication via `VDL2_API_KEY`.
- Configurable CORS origins via `VDL2_CORS_ORIGINS`.
- systemd units for `dumpvdl2` and `vdl2-api` with sandboxing.
- `AGENTS.md` — machine-readable project context for AI coding agents.
- `CONTRIBUTING.md` — development and contribution guide.
- `CHANGELOG.md` — this file.
