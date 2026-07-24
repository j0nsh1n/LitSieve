"""Pydantic request models for the HTTP API."""

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query_text: str
    top_k: int = 10
    sort_by: str = "similarity"
    cluster_filter: Optional[List[int]] = None
    source_filter: Optional[List[str]] = None
    # When true, slightly prefer abstracts that mention the user's PICO terms.
    pico_boost: bool = False
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    # Blend TF-IDF word overlap with embedding similarity (default on).
    lexical_boost: bool = True


class SeedSearchRequest(BaseModel):
    seed: str
    top_k: int = 10
    cluster_filter: Optional[List[int]] = None
    source_filter: Optional[List[str]] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    lexical_boost: bool = True


class StarredSearchRequest(BaseModel):
    top_k: int = 10
    source_filter: Optional[List[str]] = None
    cluster_filter: Optional[List[int]] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None


class MultiFetchRequest(BaseModel):
    sources: List[str]
    query: str
    max_results: int = Field(default=100, ge=1, le=1000)
    email: Optional[str] = None
    # True = wipe collection first (default classroom "start fresh").
    # False = append / update without clearing.
    clear_first: bool = True
    # wait=true: block until done (tests / legacy). Default: 202 + poll progress.
    wait: bool = False


class EmbeddingsRequest(BaseModel):
    model: str = "general"
    # Skip articles that already have vectors (unless the model changes).
    only_missing: bool = True
    wait: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_password_confirm: str


class NoteRequest(BaseModel):
    article_id: str
    source: str
    note: Optional[str] = None
    starred: Optional[bool] = None


class AIArticleRequest(BaseModel):
    """Identify one paper in the active library for optional AI assist."""
    article_id: str
    source: str
    # When true, store refined key_points in the library (overwrites extractive).
    # API convenience only — the UI saves the displayed points via
    # /api/ai/key-points instead, so a second generation can't diverge from
    # what the student approved.
    save_key_points: bool = False


class AISaveKeyPointsRequest(BaseModel):
    """Persist the AI key points the student actually saw (no regeneration)."""
    article_id: str
    source: str
    key_points: List[str]


class AIAskRequest(BaseModel):
    article_id: str
    source: str
    question: str


class AISettingsUpdate(BaseModel):
    """Server-wide AI deploy settings (keys stored in user_data/ai_settings.json)."""
    llm_provider: Optional[str] = None
    ollama_host: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_models_dir: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_timeout_seconds: Optional[str] = None


class CoverageRequest(BaseModel):
    topics: Optional[List[str]] = None


class ClusterRequest(BaseModel):
    # None (or <= 0) means auto-select the count by silhouette score.
    n_clusters: Optional[int] = None
    # Density (HDBSCAN) is the default: it finds the topic count itself and sets
    # outliers aside, which beats a guessed/auto k on real corpora.
    method: str = "hdbscan"


class DuplicateRequest(BaseModel):
    threshold: float = 0.98


class ScreeningItem(BaseModel):
    article_id: str
    source: str


class ScreeningRequest(BaseModel):
    items: List[ScreeningItem]
    action: str = Field(default="exclude", pattern="^(exclude|include)$")
    # Exclusion reason code (see screening_reasons.EXCLUSION_REASONS).
    reason: Optional[str] = "manual"


class ClusterScreeningRequest(BaseModel):
    action: str = Field(default="exclude", pattern="^(exclude|include)$")
    reason: Optional[str] = "cluster"


class SampleCorpusRequest(BaseModel):
    # True = wipe collection first (demo reset). False = append samples.
    clear_first: bool = True


class LibraryCreateRequest(BaseModel):
    name: str = Field(default="New library", min_length=1, max_length=64)


class LibraryRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class LibrarySwitchRequest(BaseModel):
    library_id: str


class ResolveDuplicatesRequest(BaseModel):
    threshold: float = Field(default=0.98, ge=0.5, le=1.0)


class DeleteAccountRequest(BaseModel):
    password: str


class ShareCreateRequest(BaseModel):
    library_id: Optional[str] = None
    expires_days: Optional[int] = Field(default=14, ge=1, le=365)
    max_uses: Optional[int] = Field(default=None, ge=1, le=10000)
    include_embeddings: bool = True


class ExportArticleKey(BaseModel):
    article_id: str
    source: str


class ExportSelectionRequest(BaseModel):
    """Export an ordered list of library papers (e.g. current search hits)."""
    format: str = "ris"  # ris | bibtex | csv | txt
    items: List[ExportArticleKey] = Field(default_factory=list)


class ShareJoinRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)
