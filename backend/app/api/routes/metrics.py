"""Prometheus scrape endpoint (V2 Module 7).

Unauthenticated, like /health -- standard operational practice (Prometheus
itself has no concept of presenting a bearer token when scraping), and
nothing exposed here is per-user or sensitive: aggregate counts and
duration buckets, never raw business data. A real production deployment
would restrict this at the network layer (only the Prometheus scrape
target can reach it) rather than behind application-level auth, the same
way a real deployment would put a firewall in front of /health.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
