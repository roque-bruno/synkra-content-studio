"""Pydantic models para request/response da API — Content Studio v2.0."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# --- Health & Dashboard ---

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"
    preview_mode: bool = True
    api_key_configured: bool = False


class DashboardStats(BaseModel):
    total_vdps: int = 0
    images_generated: int = 0
    total_size_mb: float = 0.0
    compositions: int = 0
    preview_mode: bool = True
    products_available: int = 0
    logos_available: int = 0
    claims_available: int = 0
    pieces_in_production: int = 0
    pieces_pending_review: int = 0


# --- Assets ---

class AssetItem(BaseModel):
    name: str
    path: str
    url: str
    size_kb: float = 0.0
    category: str = ""


class AssetCategory(BaseModel):
    category: str
    items: list[AssetItem] = []


class ClaimItem(BaseModel):
    claim_id: str
    texto: str
    fonte: str = ""
    status: str = "APROVADO"
    produto: str = ""


# --- VDP ---

class VDPSummary(BaseModel):
    file_name: str
    file_path: str = ""
    produto: str
    marca: str
    conceito: str
    formato: str
    png_referencia: str
    prompt_length: int
    claims_count: int
    criterios_count: int
    is_salk: bool
    is_mendel: bool
    slug: str


class VDPDetail(VDPSummary):
    prompt_nb2: str
    claims: list[ClaimItem] = []
    criterios: list[str] = []
    canva_headline: str = ""
    canva_logo: str = ""
    canva_spec_line: str = ""
    canva_anvisa: str = ""
    canva_template: str = ""


class VDPCreateRequest(BaseModel):
    produto: str
    marca: str = "salk"
    conceito: str
    formato: str = "1080x1350"
    png_referencia: str
    prompt_nb2: str
    claims: list[str] = []
    canva_headline: str = ""
    canva_logo: str = ""
    canva_spec_line: str = ""
    canva_anvisa: str = ""
    canva_template: str = "hero-shot"
    criterios: list[str] = []


# --- Prompt Builder ---

class PromptPreviewRequest(BaseModel):
    product_type: str
    scene_description: str
    lighting_preset: str = "dramatic_three_point"
    camera_preset: str = "dramatic_studio"
    surface_preset: str = "reflective_black"
    style: str = ""
    mood: str = ""
    is_lev: bool = False
    width: int = 1080
    height: int = 1350


class PromptPreviewResponse(BaseModel):
    prompt: str
    char_count: int
    presets_used: dict[str, str]


# --- Generation ---

class GenerateRequest(BaseModel):
    vdp_path: str
    output_subdir: str = ""


class GenerationResultResponse(BaseModel):
    success: bool
    produto: str
    attempts: int
    elapsed_seconds: float
    output_path: str = ""
    output_url: str = ""
    error: str = ""


# --- Calendar v2 ---

class CalendarSlot(BaseModel):
    id: str = ""
    day: str
    time: str = ""
    platform: str
    format: str = ""
    product: str = ""
    pillar: str = ""
    brand: str = "salk"
    status: str = "planned"
    piece_id: str = ""
    notes: str = ""
    persona_target: str = ""


class CalendarWeek(BaseModel):
    week_id: str
    brand: str = "salk"
    year: int = 2026
    status: str = "draft"
    slots: list[CalendarSlot] = []


# --- Production Board (Tempo) ---

class ProductionPiece(BaseModel):
    id: str = ""
    title: str
    brand: str = "salk"
    product: str = ""
    pillar: str = ""
    platform: str = ""
    format: str = ""
    stage: str = "briefing"  # briefing|copy|visual|review|approved|published
    assignee: str = ""
    vdp_path: str = ""
    copy_text: str = ""
    claims_used: list[str] = []
    hashtags: list[str] = []
    persona_target: str = ""
    master_id: str = ""
    is_derivative: bool = False
    calendar_slot_id: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class PieceStageUpdate(BaseModel):
    stage: str
    notes: str = ""


# --- Copy Editor (Helix) ---

class CopyDraft(BaseModel):
    piece_id: str
    text: str
    headline: str = ""
    cta: str = ""
    hashtags: list[str] = []
    claims_used: list[str] = []
    persona_target: str = ""
    platform: str = ""
    char_count: int = 0


# --- Compliance (Shield) ---

class ComplianceCheckRequest(BaseModel):
    text: str
    brand: str = "salk"
    product: str = ""


class ComplianceResult(BaseModel):
    passed: bool
    violations: list[dict] = []
    warnings: list[dict] = []
    claims_valid: bool = True
    etrus_blocked: bool = False


# --- Review Queue (Lens) ---

class ReviewItem(BaseModel):
    piece_id: str
    review_type: str = "editorial"  # editorial|visual|compliance|final
    verdict: str = "pending"  # pending|approved|rejected|revision
    comments: str = ""
    reviewer: str = ""
    checklist: list[dict] = []


class ReviewUpdate(BaseModel):
    verdict: str = "pending"
    comments: str = ""


# --- Performance (Pulse) ---

class PerformanceEntry(BaseModel):
    piece_id: str
    platform: str
    published_at: str = ""
    impressions: int = 0
    reach: int = 0
    engagement: int = 0
    clicks: int = 0
    saves: int = 0
    shares: int = 0
    comments_count: int = 0
    notes: str = ""


class PresetInfo(BaseModel):
    name: str
    details: dict[str, str]
