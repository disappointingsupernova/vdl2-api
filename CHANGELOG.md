# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [1.0.0] — 2026-08-16

### Added

- Initial release.
- `dumpvdl2` JSONL spool collector with byte-offset checkpointing and hourly file rotation detection.
- SQLite persistence via SQLAlchemy ORM (`Message`, `CollectorState` mapped classes).
- WAL mode with `synchronous=NORMAL` for reliable concurrent reads.
- SHA-256 `message_hash` deduplication via `INSERT OR IGNORE`.
- 30-day configurable message retention with background cleanup thread.
- FastAPI REST API with cursor-based polling (`after_id`).
- `GET /api/v1/messages` — paginated message list with `after_id`, `limit`, `since`, `until`, `icao`, `frequency` filters.
- `GET /api/v1/messages/latest` — newest N messages.
- `GET /api/v1/aircraft` — aircraft observed within a configurable time window.
- `GET /api/v1/aircraft/{icao}/messages` — messages for a specific aircraft.
- `GET /api/v1/health` — service and database health check.
- `GET /api/v1/stats` — message counts by time window and frequency.
- Optional `X-API-Key` authentication via `VDL2_API_KEY` environment variable.
- Configurable CORS origins via `VDL2_CORS_ORIGINS`.
- systemd units for `dumpvdl2` and `vdl2-api` with sandboxing (`ProtectSystem`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`).
- 48 automated tests covering parsing, database, collector, API, and authentication.
- `AGENTS.md` machine-readable project context for AI coding agents.
- `CONTRIBUTING.md` development and contribution guide.
