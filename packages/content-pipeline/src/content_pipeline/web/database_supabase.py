"""
Database Supabase — PostgreSQL persistence layer via Supabase.

Drop-in replacement for StudioDatabase (SQLite) when Supabase is configured.
Uses supabase-py client with service_role key for full access.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)


class SupabaseDatabase:
    """Supabase (PostgreSQL) database for Content Studio persistence."""

    def __init__(self, url: str, key: str) -> None:
        self.client: Client = create_client(url, key)
        logger.info("Supabase database connected: %s", url[:30] + "...")

    def migrate_from_json(self, studio_dir) -> None:
        """No-op for Supabase — migrations are done via SQL Editor."""
        pass

    # ------------------------------------------------------------------
    # Pieces (Production Board)
    # ------------------------------------------------------------------

    def list_pieces(self, stage: str = "", brand: str = "") -> list[dict]:
        query = self.client.table("pieces").select("*")
        if stage:
            query = query.eq("stage", stage)
        if brand:
            query = query.eq("brand", brand)
        query = query.order("updated_at", desc=True)
        result = query.execute()
        return [self._parse_piece(r) for r in result.data]

    def create_piece(self, data: dict, use_existing_id: bool = False) -> dict:
        piece_id = data.get("id") if use_existing_id and data.get("id") else str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        row = {
            "id": piece_id,
            "title": data.get("title", ""),
            "brand": data.get("brand", "salk"),
            "product": data.get("product", ""),
            "pillar": data.get("pillar", ""),
            "platform": data.get("platform", ""),
            "format": data.get("format", ""),
            "stage": data.get("stage", "briefing"),
            "assignee": data.get("assignee", ""),
            "vdp_path": data.get("vdp_path", ""),
            "copy_text": data.get("copy_text", ""),
            "claims_used": data.get("claims_used", []),
            "hashtags": data.get("hashtags", []),
            "persona_target": data.get("persona_target", ""),
            "master_id": data.get("master_id", ""),
            "is_derivative": bool(data.get("is_derivative", False)),
            "calendar_slot_id": data.get("calendar_slot_id", ""),
            "notes": data.get("notes", ""),
            "created_at": data.get("created_at", now),
            "updated_at": data.get("updated_at", now),
        }
        result = self.client.table("pieces").upsert(row).execute()
        return self._parse_piece(result.data[0]) if result.data else {"id": piece_id}

    def get_piece(self, piece_id: str) -> Optional[dict]:
        result = self.client.table("pieces").select("*").eq("id", piece_id).execute()
        if result.data:
            return self._parse_piece(result.data[0])
        return None

    def update_piece_stage(self, piece_id: str, stage: str, notes: str = "") -> Optional[dict]:
        update_data: dict = {"stage": stage, "updated_at": datetime.utcnow().isoformat()}
        if notes:
            update_data["notes"] = notes
        result = self.client.table("pieces").update(update_data).eq("id", piece_id).execute()
        if result.data:
            return self._parse_piece(result.data[0])
        return None

    def update_piece(self, piece_id: str, data: dict) -> Optional[dict]:
        update_data = {k: v for k, v in data.items() if k != "id"}
        if not update_data:
            return self.get_piece(piece_id)
        update_data["updated_at"] = datetime.utcnow().isoformat()
        result = self.client.table("pieces").update(update_data).eq("id", piece_id).execute()
        if result.data:
            return self._parse_piece(result.data[0])
        return None

    def delete_piece(self, piece_id: str) -> bool:
        result = self.client.table("pieces").delete().eq("id", piece_id).execute()
        return len(result.data) > 0

    def _parse_piece(self, row: dict) -> dict:
        """Normaliza dados do Supabase para o formato esperado."""
        # Handle NULL/None → default values
        if row.get("claims_used") is None:
            row["claims_used"] = []
        elif isinstance(row.get("claims_used"), str):
            row["claims_used"] = json.loads(row["claims_used"])
        if row.get("hashtags") is None:
            row["hashtags"] = []
        elif isinstance(row.get("hashtags"), str):
            row["hashtags"] = json.loads(row["hashtags"])
        row["is_derivative"] = bool(row.get("is_derivative", False))
        # Ensure text fields are never None (frontend expects strings)
        for field in ("product", "assignee", "vdp_path", "copy_text", "persona_target",
                       "master_id", "calendar_slot_id", "notes", "pillar", "platform", "format"):
            if row.get(field) is None:
                row[field] = ""
        # Extract image_url from notes JSON to top-level for kanban cards
        notes_str = row.get("notes", "")
        if notes_str and isinstance(notes_str, str):
            try:
                notes_obj = json.loads(notes_str)
                if isinstance(notes_obj, dict):
                    if notes_obj.get("image_url"):
                        row["image_url"] = notes_obj["image_url"]
                    if notes_obj.get("video_url"):
                        row["video_url"] = notes_obj["video_url"]
            except (json.JSONDecodeError, TypeError):
                pass
        return row

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def list_reviews(self, verdict: str = "") -> list[dict]:
        query = self.client.table("reviews").select("*")
        if verdict:
            query = query.eq("verdict", verdict)
        query = query.order("created_at", desc=True)
        result = query.execute()
        return [self._parse_review(r) for r in result.data]

    def create_review(self, data: dict, use_existing_id: bool = False) -> dict:
        review_id = data.get("id") if use_existing_id and data.get("id") else str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        row = {
            "id": review_id,
            "piece_id": data.get("piece_id", ""),
            "review_type": data.get("review_type", "editorial"),
            "verdict": data.get("verdict", "pending"),
            "comments": data.get("comments", ""),
            "reviewer": data.get("reviewer", ""),
            "checklist": data.get("checklist", []),
            "created_at": data.get("created_at", now),
            "updated_at": data.get("updated_at", ""),
        }
        result = self.client.table("reviews").upsert(row).execute()
        return self._parse_review(result.data[0]) if result.data else {"id": review_id}

    def get_review(self, review_id: str) -> Optional[dict]:
        result = self.client.table("reviews").select("*").eq("id", review_id).execute()
        if result.data:
            return self._parse_review(result.data[0])
        return None

    def update_review(self, review_id: str, verdict: str, comments: str = "") -> Optional[dict]:
        result = (
            self.client.table("reviews")
            .update({"verdict": verdict, "comments": comments, "updated_at": datetime.utcnow().isoformat()})
            .eq("id", review_id)
            .execute()
        )
        if result.data:
            return self._parse_review(result.data[0])
        return None

    def _parse_review(self, row: dict) -> dict:
        if isinstance(row.get("checklist"), str):
            row["checklist"] = json.loads(row["checklist"])
        return row

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def list_metrics(self) -> list[dict]:
        result = (
            self.client.table("metrics")
            .select("*")
            .order("recorded_at", desc=True)
            .execute()
        )
        return result.data

    def save_metric(self, data: dict, use_existing_id: bool = False) -> dict:
        metric_id = data.get("id") if use_existing_id and data.get("id") else str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        row = {
            "id": metric_id,
            "piece_id": data.get("piece_id", ""),
            "platform": data.get("platform", ""),
            "published_at": data.get("published_at", None),
            "impressions": data.get("impressions", 0),
            "reach": data.get("reach", 0),
            "engagement": data.get("engagement", 0),
            "clicks": data.get("clicks", 0),
            "saves": data.get("saves", 0),
            "shares": data.get("shares", 0),
            "comments_count": data.get("comments_count", 0),
            "notes": data.get("notes", ""),
            "recorded_at": data.get("recorded_at", now),
        }
        result = self.client.table("metrics").upsert(row).execute()
        return result.data[0] if result.data else {"id": metric_id, **row}

    def get_performance_summary(self) -> dict:
        # Usa a view performance_summary criada na migration
        result = self.client.table("performance_summary").select("*").execute()
        summary: dict = {}
        for row in result.data:
            platform = row.pop("platform", "unknown")
            summary[platform] = row
        return summary

    # ------------------------------------------------------------------
    # Calendars
    # ------------------------------------------------------------------

    def list_calendars(self) -> list[str]:
        result = (
            self.client.table("calendars")
            .select("week_id")
            .order("week_id")
            .execute()
        )
        return [r["week_id"] for r in result.data]

    def load_calendar(self, week_id: str) -> Optional[dict]:
        result = (
            self.client.table("calendars")
            .select("*")
            .eq("week_id", week_id)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        if isinstance(row.get("slots"), str):
            row["slots"] = json.loads(row["slots"])
        return row

    def save_calendar(self, week_id: str, data: dict) -> None:
        row = {
            "week_id": week_id,
            "brand": data.get("brand", "salk"),
            "year": data.get("year", 2026),
            "status": data.get("status", "draft"),
            "slots": data.get("slots", []),
        }
        self.client.table("calendars").upsert(row).execute()
