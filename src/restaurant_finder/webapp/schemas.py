"""Modèles pydantic de l'API du panel web (requêtes/réponses HTTP)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PointInput(BaseModel):
    """Un lieu cliqué sur la carte, avec son rayon de recherche."""

    latitude: float
    longitude: float
    radius_meters: float = 800.0


class SearchRequest(BaseModel):
    """Corps de la requête `POST /api/search`."""

    cities: list[str] = Field(default_factory=list)
    points: list[PointInput] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    limit: int | None = None
    formats: list[str] = Field(default_factory=lambda: ["csv", "xlsx"])
    enrich_instagram: bool = True
    only_with_instagram: bool = False
    include_chains: bool = False
    max_followers: int = 1000
    keep_unknown_followers: bool = False


class ResultRow(BaseModel):
    """Une ligne de résultat affichée dans le tableau du panel."""

    name: str
    instagram: str | None = None
    instagram_followers: int | None = None
    address: str
    city: str
    category: str


class JobStatusResponse(BaseModel):
    """Réponse de `GET /api/jobs/{job_id}` : état d'avancement d'une recherche."""

    job_id: str
    status: str
    message: str = ""
    progress_done: int = 0
    progress_total: int = 0
    results: list[ResultRow] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    error: str | None = None
