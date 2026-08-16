# AGENTS.md — AI agent context for vdl2-api

This file provides structured context for AI coding agents (Amazon Q,
GitHub Copilot, Cursor, etc.) working on this repository. It describes
the project purpose, architecture, key conventions, and the areas most
likely to need attention.

---

## What this project is

A lightweight Python REST API service for Raspberry Pi that:

1. Receives decoded VDL Mode 2 (VHF Data Link) aviation messages from
   `dumpvdl2` via an append-only JSONL spool file.
2. Persists every message to a local SQLite database.
3. Exposes the messages through a FastAPI REST API using a cursor-based
   polling model (`GET /api/v1/messages?after_id=N`).

VDL Mode 2 is a digital datalink used by commercial aircraft to exchange
ACARS, CPDLC, ADS-C, and other operational messages with ground stations.

---

## Repository layout

```
app/
  main.py        — FastAPI app factory (_create_app), lifespan, CORS, auth wiring
  config.py      — All settings via VDL2_* env vars (pydantic-settings, lru_cache)
  database.py    — SQLAlchemy ORM models (Message, CollectorState), thread-safe
                   engine factory (_factories_lock), get_session() context manager
  models.py      — query_messages() — the single shared ORM query helper used by routes
  schemas.py     — Pydantic response models (MessageOut, MessagesResponse, etc.)
  parser.py      — Extracts fields from raw dumpvdl2 JSON; SHA-256 hash of raw_json
  collector.py   — Tails the JSONL spool, batch inserts, checkpoints byte offset,
                   detects hourly rotation, runs retention cleanup
  auth.py        — Optional X-API-Key authentication dependency; logs auth failures
  routes/
    messages.py  — GET /api/v1/messages (since/until validated as datetime), /latest
    aircraft.py  — GET /api/v1/aircraft, GET /api/v1/aircraft/{icao}/messages
    stats.py     — GET /api/v1/stats
    health.py    — GET /api/v1/health

scripts/
  install.sh     — Full installation (checks deps including Python 3.11-3.13
                   version gate, creates user, creates venv, installs units).
                   Respects PYTHON env var: sudo bash -c 'PYTHON=python3.12 bash /opt/vdl2-api/scripts/install.sh'
                   Idempotent.
  update.sh      — git pull + pip install + unit update + service restart + health check

systemd/
  dumpvdl2.service   — Runs dumpvdl2, writes JSONL spool
  vdl2-api.service   — Runs the Python API + collector (After=dumpvdl2.service)

tests/
  fixtures/
    sample_messages.jsonl  — Representative dumpvdl2 JSON lines (4 messages,
                             multiple protocol variants)
  conftest.py        — Documents test isolation approach and known gaps
  test_parser.py     — 12 tests: field extraction, hashing, malformed input
  test_database.py   —  4 tests: schema, WAL mode, uniqueness, autoincrement
  test_collector.py  — 11 tests: drain, checkpoint, rotation, retention, restart
  test_api.py        — 19 tests: all endpoints, cursor, filters, since/until validation
  test_auth.py       —  5 tests: auth enabled/disabled, missing/invalid key
  test_cors.py       —  3 tests: CORS middleware configuration
                     — 54 tests total
```

---

## Key design decisions

### Cursor-based polling, not timestamp windows

The primary API pattern is `GET /api/v1/messages?after_id=N`. The `id`
column is a SQLite AUTOINCREMENT integer — monotonically increasing,
permanent, unique. Clients store their last processed `id` and request
everything after it. This means:

- A client that stops polling for an hour loses nothing.
- Multiple independent clients can read the same messages.
- Messages are never deleted because a client hasn't fetched them.

**Do not change this to a timestamp-based window** without understanding
the implications for client reliability.

### JSONL spool as ingestion buffer

`dumpvdl2` writes decoded JSON to an append-only JSONL file. The Python
collector tails this file using `readline()` + `tell()` — **not** `for
line in fh`, which disables `tell()`. The byte offset is checkpointed to
the `collector_state` table after each successful batch. On restart, the
collector seeks to the last saved offset.

### Batch inserts in drain()

`drain()` reads all available lines into a list, then inserts the entire
batch in a single `session.commit()`. This keeps the commit count at one
per poll cycle, which matters on a Raspberry Pi SD card. The trade-off is
that a crash mid-drain re-processes from the last checkpoint — `INSERT OR
IGNORE` on `message_hash` makes that safe. See the docstring in
`collector.py` for the memory bound discussion.

### Duplicate protection

Every message gets a SHA-256 hash of its raw JSON stored as `message_hash`
(UNIQUE constraint). Inserts use `INSERT OR IGNORE`, so replaying the spool
after a crash produces no duplicates.

### File rotation

`dumpvdl2` rotates the JSONL file hourly. The collector detects rotation
by comparing the inode of the live spool path against the inode of the
currently open file handle. On rotation, it drains the old file before
opening the new one.

### ORM layer

The project uses SQLAlchemy ORM (not Core). The two mapped classes are
`Message` and `CollectorState` in `app/database.py`. All queries go
through `get_session()`, a context manager that commits on exit and rolls
back on exception. The session factory is per-database-path and protected
by a `threading.Lock` (`_factories_lock`).

### App construction

The FastAPI app is built inside `_create_app()` rather than at module
scope. This defers `get_settings()` until `_create_app()` runs, which
means tests can patch `get_settings` before the app is constructed. The
module-level `app = _create_app()` is the production singleton. CORS
middleware is applied during construction, not at request time — CORS
tests must call `_create_app()` inside the patch context.

### Settings

All configuration is via `VDL2_*` environment variables. The `Settings`
class in `app/config.py` uses pydantic-settings. `get_settings()` is
decorated with `@lru_cache` — in tests, patch `get_settings` at the
module level where it is used (e.g. `app.routes.messages.get_settings`),
not at `app.config.get_settings`. See `tests/conftest.py` for details.

### Authentication

Optional. Set `VDL2_API_KEY` to a non-empty string to require
`X-API-Key: <value>` on all requests. When empty, all requests are
allowed. The dependency is applied at the router level in `main.py`.
Auth failures are logged at WARNING with the reason (missing vs invalid)
but never the key value.

### Graceful shutdown

`run_collector()` accepts a `stop_event: threading.Event`. The lifespan
sets the event after `yield`, then joins the collector thread with a
10-second timeout. If the join times out, the daemon flag kills the thread
on process exit — the WAL journal and `INSERT OR IGNORE` make this safe.

---

## Data model

### `messages` table

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Autoincrement — the public API cursor |
| `received_at` | TEXT | UTC ISO 8601, from dumpvdl2 `t` field |
| `received_at_epoch_ms` | INTEGER | Unix ms, nullable |
| `station_id` | TEXT | dumpvdl2 `--station-id` value |
| `frequency_hz` | INTEGER | RF frequency in Hz |
| `source_icao` | TEXT | AVLC source address, uppercase hex |
| `destination_icao` | TEXT | AVLC destination address, uppercase hex |
| `direction` | TEXT | `downlink` or `uplink` |
| `message_type` | TEXT | ACARS label (e.g. `H1`, `Q0`) |
| `aircraft_registration` | TEXT | From ACARS `reg` field |
| `flight_id` | TEXT | From ACARS `flight` field |
| `message_text` | TEXT | From ACARS `msg_text` or `text` field |
| `raw_json` | TEXT | Complete original dumpvdl2 JSON, verbatim |
| `inserted_at` | TEXT | UTC ISO 8601, time of Python ingestion |
| `message_hash` | TEXT UNIQUE | SHA-256 of raw_json |

### `collector_state` table

| Column | Type | Notes |
|---|---|---|
| `spool_path` | TEXT PK | Absolute path to the spool file |
| `byte_offset` | INTEGER | Last successfully processed byte position |
| `updated_at` | TEXT | UTC ISO 8601 |

---

## dumpvdl2 JSON structure

The upstream JSON produced by dumpvdl2 looks like this (simplified):

```json
{
  "t": 1786897449,
  "freq": 136975000,
  "station_id": "adsb-pi",
  "avlc": {
    "src": { "addr": "4CADF7", "type": "Aircraft" },
    "dst": { "addr": "1099CA", "type": "Ground station" },
    "acars": {
      "label": "H1",
      "reg": "EIEXS",
      "flight": "EI501",
      "msg_text": "#DFB/WRG POSRPT"
    }
  }
}
```

ACARS may be nested under `avlc.acars`, `avlc.x25.acars`, `avlc.clnp.acars`,
or `avlc.idrp.acars` depending on the protocol variant. Many messages carry
no ACARS payload at all — the ACARS fields in the database will be NULL.
The complete JSON is always stored in `raw_json`.

---

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

54 tests. Tests use `tmp_path` fixtures for isolated SQLite databases. No
external services are required. The FastAPI `TestClient` is used for API
tests with `get_settings` and `get_session` patched to point at the test
database.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `VDL2_API_HOST` | `0.0.0.0` | Uvicorn bind address |
| `VDL2_API_PORT` | `5001` | Uvicorn port |
| `VDL2_DATABASE` | `/var/lib/vdl2/vdl2.db` | SQLite database path |
| `VDL2_SPOOL` | `/var/lib/vdl2/messages.jsonl` | dumpvdl2 JSONL output path |
| `VDL2_RETENTION_DAYS` | `30` | Days to retain messages |
| `VDL2_CORS_ORIGINS` | _(empty)_ | Comma-separated allowed CORS origins |
| `VDL2_API_KEY` | _(empty)_ | X-API-Key value; empty disables auth |

---

## What to be careful about

- **Do not change the cursor model.** `after_id` must remain a database
  `id`, not a timestamp. Clients depend on this for reliable delivery.
- **Do not use `for line in fh` in the collector.** Python's file iterator
  disables `tell()`. Use `readline()` in a `while True` loop.
- **All timestamps must be UTC ISO 8601 ending in `Z`.** The `_utc_iso()`
  helper in `parser.py` handles this.
- **The collector runs in a daemon thread.** Do not introduce blocking
  calls into the FastAPI event loop from the collector.
- **`get_settings()` is `lru_cache`'d.** In tests, patch the reference
  at the point of use, not at `app.config`. See `tests/conftest.py`.
- **CORS tests must use `_create_app()`.** The module-level `app` singleton
  has CORS configured from the real settings. Tests that need different
  CORS origins must call `_create_app()` inside the patch context.
- **`since`/`until` are validated as `datetime`.** FastAPI returns 422 for
  malformed values. Do not change these back to `str`.
- **Python 3.11–3.13 only.** `pydantic-core` uses PyO3 which has a hard
  maximum of Python 3.13. The install script enforces this. On Ubuntu
  26.04 (system Python 3.14), use the deadsnakes PPA and pass
  `sudo bash -c 'PYTHON=python3.12 bash /opt/vdl2-api/scripts/install.sh'`.
