from app.schemas.health import HealthResponse


def get_health() -> HealthResponse:
    return HealthResponse(status="ok", message="SentinelP2P API is running")
