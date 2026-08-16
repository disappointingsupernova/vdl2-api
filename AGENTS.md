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
  main.py        — FastAPI app factory, lifespan (collector + cleanup threads), CORS, auth
  config.py      — All settings via VDL2_* env vars (pydantic-settings)
  database.py    — SQLAlchemy ORM models (Message, CollectorState), engine factory, get_session()
  models.py      — query_messages() — the single shared ORM query helper used by routes
  schemas.py     — Pydantic response models (MessageOut, MessagesResponse, etc.)
  parser.py      — Extracts fields from raw dumpvdl2 JSON; produces dicts for DB insertion
  collector.py   — Tails the JSONL spool, checkpoints byte offset, inserts into DB
  auth.py        — Optional X-API-Key authentication dependency
  routes/
    messages.py  — GET /api/v1/messages, GET /api/v1/messages/latest
    aircraft.py  — GET /api/v1/aircraft, GET /api/v1/aircraft/{icao}/messages
    stats.py     — GET /api/v1/stats
    health.py    — GET /api/v1/health

tests/
  fixtures/
    sample_messages.jsonl  — Representative dumpvdl2 JSON lines for testing
  test_parser.py     — Unit tests for parser.py
  test_database.py   — Schema, WAL mode, uniqueness constraints
  test_collector.py  — Drain, checkpoint, deduplication, retention, restart recovery
  test_api.py        — Full API integration tests via FastAPI TestClient
  test_auth.py       — Authentication enabled/disabled behaviour

systemd/
  dumpvdl2.service   — Runs dumpvdl2, writes JSONL spool
  vdl2-api.service   — Runs the Python API + collector
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

Do not change this to a timestamp-based window without understanding the
implications for client reliability.

### JSONL spool as ingestion buffer

`dumpvdl2` writes decoded JSON to an append-only JSONL file. The Python
collector tails this file using `readline()` + `tell()` (not `for line in
fh`, which disables `tell()`). The byte offset is checkpointed to the
`collector_state` table after every line. On restart, the collector seeks
to the last saved offset.

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
by a `threading.Lock`.

### Settings

All configuration is via `VDL2_*` environment variables. The `Settings`
class in `app/config.py` uses pydantic-settings. `get_settings()` is
decorated with `@lru_cache` — in tests, patch `get_settings` at the
module level where it is used (e.g. `app.routes.messages.get_settings`),
not at `app.config.get_settings`.

### Authentication

Optional. Set `VDL2_API_KEY` to a non-empty string to require
`X-API-Key: <value>` on all requests. When empty, all requests are
allowed. The dependency is applied at the router level in `main.py`.

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

Tests use `tmp_path` fixtures for isolated SQLite databases. No external
services are required. The FastAPI TestClient is used for API tests with
`get_settings` and `get_session` patched to point at the test database.

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
  at the point of use, not at `app.config`.
