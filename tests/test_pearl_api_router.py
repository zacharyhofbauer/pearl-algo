"""
Tests for Pearl AI API router configuration.
"""

from pearl_ai.api_router import create_pearl_router
from pearl_ai.brain import PearlBrain


def test_metrics_sources_route_unique():
    """Ensure /metrics/sources is defined exactly once."""
    router = create_pearl_router(PearlBrain(enable_local=False, enable_claude=False))
    matching_routes = [
        route
        for route in router.routes
        if getattr(route, "path", None) == "/metrics/sources" and "GET" in getattr(route, "methods", set())
    ]
    assert len(matching_routes) == 1
