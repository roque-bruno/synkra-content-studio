"""
Database — SQLite persistence layer for Content Studio v2.0.

Replaces JSON file persistence with proper database.
Uses standard sqlite3 (sync) for compatibility with the existing sync services.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pieces (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT 'salk',
    product TEXT DEFAULT '',
    pillar TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    format TEXT DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'briefing',
    assignee TEXT DEFAULT '',
    vdp_path TEXT DEFAULT '',
    copy_text TEXT DEFAULT '',
    claims_used TEXT DEFAULT '[]',
    hashtags TEXT DEFAULT '[]',
    persona_target TEXT DEFAULT '',
    master_id TEXT DEFAULT '',
    is_derivative INTEGER DEFAULT 0,
    calendar_slot_id TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pieces_stage ON pieces(stage);
CREATE INDEX IF NOT EXISTS idx_pieces_brand ON pieces(brand);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    piece_id TEXT DEFAULT '',
    review_type TEXT DEFAULT 'editorial',
    verdict TEXT DEFAULT 'pending',
    comments TEXT DEFAULT '',
    reviewer TEXT DEFAULT '',
    checklist TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_reviews_verdict ON reviews(verdict);

CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    piece_id TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    published_at TEXT DEFAULT '',
    impressions INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    engagement INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_platform ON metrics(platform);

CREATE TABLE IF NOT EXISTS calendars (
    week_id TEXT PRIMARY KEY,
    brand TEXT DEFAULT 'salk',
    year INTEGER DEFAULT 2026,
    status TEXT DEFAULT 'draft',
    slots TEXT DEFAULT '[]',
    updated_at TEXT NOT NULL
);
"""


class StudioDatabase:
    """SQLite database for Content Studio persistence."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("Database initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Migration: JSON → SQLite
    # ------------------------------------------------------------------

    def migrate_from_json(self, studio_dir: Path) -> None:
        """Import existing JSON files into SQLite (idempotent)."""
        self._migrate_json_file(studio_dir / "pieces.json", "pieces")
        self._migrate_json_file(studio_dir / "reviews.json", "reviews")
        self._migrate_json_file(studio_dir / "metrics.json", "metrics")

        calendars_dir = studio_dir / "calendars"
        if calendars_dir.exists():
            for cal_file in calendars_dir.glob("*.json"):
                try:
                    data = json.loads(cal_file.read_text(encoding="utf-8"))
                    self.save_calendar(cal_file.stem, data)
                except Exception as e:
                    logger.warning("Failed to migrate calendar %s: %s", cal_file, e)

    def _migrate_json_file(self, json_path: Path, table: str) -> None:
        if not json_path.exists():
            return
        try:
            items = json.loads(json_path.read_text(encoding="utf-8"))
            if not items:
                return
            with self._get_conn() as conn:
                existing = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if existing > 0:
                    logger.info("Table %s already has data, skipping migration", table)
                    return
            for item in items:
                if table == "pieces":
                    self.create_piece(item, use_existing_id=True)
                elif table == "reviews":
                    self.create_review(item, use_existing_id=True)
                elif table == "metrics":
                    self.save_metric(item, use_existing_id=True)
            logger.info("Migrated %d records from %s to %s", len(items), json_path.name, table)
        except Exception as e:
            logger.warning("Failed to migrate %s: %s", json_path, e)

    # ------------------------------------------------------------------
    # Pieces (Production Board)
    # ------------------------------------------------------------------

    def list_pieces(self, stage: str = "", brand: str = "") -> list[dict]:
        query = "SELECT * FROM pieces WHERE 1=1"
        params: list = []
        if stage:
            query += " AND stage = ?"
            params.append(stage)
        if brand:
            query += " AND brand = ?"
            params.append(brand)
        query += " ORDER BY updated_at DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._piece_to_dict(r) for r in rows]

    def create_piece(self, data: dict, use_existing_id: bool = False) -> dict:
        piece_id = data.get("id") if use_existing_id and data.get("id") else str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO pieces
                   (id, title, brand, product, pillar, platform, format, stage,
                    assignee, vdp_path, copy_text, claims_used, hashtags,
                    persona_target, master_id, is_derivative, calendar_slot_id,
                    notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    piece_id,
                    data.get("title", ""),
                    data.get("brand", "salk"),
                    data.get("product", ""),
                    data.get("pillar", ""),
                    data.get("platform", ""),
                    data.get("format", ""),
                    data.get("stage", "briefing"),
                    data.get("assignee", ""),
                    data.get("vdp_path", ""),
                    data.get("copy_text", ""),
                    json.dumps(data.get("claims_used", [])),
                    json.dumps(data.get("hashtags", [])),
                    data.get("persona_target", ""),
                    data.get("master_id", ""),
                    1 if data.get("is_derivative") else 0,
                    data.get("calendar_slot_id", ""),
                    data.get("notes", ""),
                    data.get("created_at", now),
                    data.get("updated_at", now),
                ),
            )
        return self.get_piece(piece_id) or {"id": piece_id}

    def get_piece(self, piece_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM pieces WHERE id = ?", (piece_id,)).fetchone()
        return self._piece_to_dict(row) if row else None

    def update_piece_stage(self, piece_id: str, stage: str, notes: str = "") -> Optional[dict]:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            if notes:
                cursor = conn.execute(
                    "UPDATE pieces SET stage=?, notes=?, updated_at=? WHERE id=?",
                    (stage, notes, now, piece_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE pieces SET stage=?, updated_at=? WHERE id=?",
                    (stage, now, piece_id),
                )
            if cursor.rowcount == 0:
                return None
        return self.get_piece(piece_id)

    # Whitelist of columns allowed in update operations
    ALLOWED_PIECE_COLUMNS = {
        "title", "brand", "product", "pillar", "platform", "format",
        "persona_target", "copy_text", "hashtags", "claims_used",
        "nb2_prompt", "image_url", "stage", "notes",
        "is_derivative", "parent_piece_id", "calendar_slot_id",
        "published_at",
    }

    def update_piece(self, piece_id: str, data: dict) -> Optional[dict]:
        existing = self.get_piece(piece_id)
        if not existing:
            return None
        now = datetime.utcnow().isoformat()
        updates = []
        params = []
        for key, value in data.items():
            if key == "id" or key not in self.ALLOWED_PIECE_COLUMNS:
                continue
            col = key
            if col in ("claims_used", "hashtags") and isinstance(value, list):
                value = json.dumps(value)
            if col == "is_derivative":
                value = 1 if value else 0
            updates.append(f"{col}=?")
            params.append(value)
        updates.append("updated_at=?")
        params.append(now)
        params.append(piece_id)

        with self._get_conn() as conn:
            conn.execute(f"UPDATE pieces SET {', '.join(updates)} WHERE id=?", params)
        return self.get_piece(piece_id)

    def delete_piece(self, piece_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM pieces WHERE id=?", (piece_id,))
            return cursor.rowcount > 0

    def _piece_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["claims_used"] = json.loads(d.get("claims_used", "[]"))
        d["hashtags"] = json.loads(d.get("hashtags", "[]"))
        d["is_derivative"] = bool(d.get("is_derivative", 0))
        return d

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def list_reviews(self, verdict: str = "") -> list[dict]:
        query = "SELECT * FROM reviews"
        params: list = []
        if verdict:
            query += " WHERE verdict = ?"
            params.append(verdict)
        query += " ORDER BY created_at DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._review_to_dict(r) for r in rows]

    def create_review(self, data: dict, use_existing_id: bool = False) -> dict:
        review_id = data.get("id") if use_existing_id and data.get("id") else str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO reviews
                   (id, piece_id, review_type, verdict, comments, reviewer, checklist, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    review_id,
                    data.get("piece_id", ""),
                    data.get("review_type", "editorial"),
                    data.get("verdict", "pending"),
                    data.get("comments", ""),
                    data.get("reviewer", ""),
                    json.dumps(data.get("checklist", [])),
                    data.get("created_at", now),
                    data.get("updated_at", ""),
                ),
            )
        return self.get_review(review_id) or {"id": review_id}

    def get_review(self, review_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return self._review_to_dict(row) if row else None

    def update_review(self, review_id: str, verdict: str, comments: str = "") -> Optional[dict]:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE reviews SET verdict=?, comments=?, updated_at=? WHERE id=?",
                (verdict, comments, now, review_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_review(review_id)

    def _review_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["checklist"] = json.loads(d.get("checklist", "[]"))
        return d

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def list_metrics(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM metrics ORDER BY recorded_at DESC").fetchall()
        return [dict(r) for r in rows]

    def save_metric(self, data: dict, use_existing_id: bool = False) -> dict:
        metric_id = data.get("id") if use_existing_id and data.get("id") else str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO metrics
                   (id, piece_id, platform, published_at, impressions, reach,
                    engagement, clicks, saves, shares, comments_count, notes, recorded_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    metric_id,
                    data.get("piece_id", ""),
                    data.get("platform", ""),
                    data.get("published_at", ""),
                    data.get("impressions", 0),
                    data.get("reach", 0),
                    data.get("engagement", 0),
                    data.get("clicks", 0),
                    data.get("saves", 0),
                    data.get("shares", 0),
                    data.get("comments_count", 0),
                    data.get("notes", ""),
                    data.get("recorded_at", now),
                ),
            )
        return {"id": metric_id, **data, "recorded_at": data.get("recorded_at", now)}

    def get_performance_summary(self) -> dict:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT platform,
                          COUNT(*) as count,
                          SUM(impressions) as total_impressions,
                          SUM(reach) as total_reach,
                          SUM(engagement) as total_engagement,
                          SUM(clicks) as total_clicks,
                          SUM(saves) as total_saves,
                          SUM(shares) as total_shares
                   FROM metrics
                   GROUP BY platform"""
            ).fetchall()

        summary: dict = {}
        for row in rows:
            d = dict(row)
            platform = d.pop("platform", "unknown")
            summary[platform] = d
        return summary

    # ------------------------------------------------------------------
    # Calendars
    # ------------------------------------------------------------------

    def list_calendars(self) -> list[str]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT week_id FROM calendars ORDER BY week_id").fetchall()
        return [r["week_id"] for r in rows]

    def load_calendar(self, week_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM calendars WHERE week_id = ?", (week_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["slots"] = json.loads(d.get("slots", "[]"))
        return d

    def save_calendar(self, week_id: str, data: dict) -> None:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO calendars (week_id, brand, year, status, slots, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(week_id)
                   DO UPDATE SET brand=excluded.brand, year=excluded.year,
                                 status=excluded.status, slots=excluded.slots,
                                 updated_at=excluded.updated_at""",
                (
                    week_id,
                    data.get("brand", "salk"),
                    data.get("year", 2026),
                    data.get("status", "draft"),
                    json.dumps(data.get("slots", [])),
                    now,
                ),
            )
