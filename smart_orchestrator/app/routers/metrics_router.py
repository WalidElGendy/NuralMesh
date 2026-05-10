"""Prometheus /prometheus endpoint for NeuralMesh Smart Orchestrator (Sprint 9)."""
from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(tags=["metrics"])


@router.get("/prometheus", response_class=Response)
async def prometheus_metrics():
    """Expose Prometheus metrics in text format."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
