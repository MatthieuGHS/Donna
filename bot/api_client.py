"""HTTP client for calling the FastAPI tools API."""

import structlog
import httpx

from config import settings

logger = structlog.get_logger(__name__)

# Limit max destructive actions per message to prevent prompt injection abuse
MAX_DESTRUCTIVE_ACTIONS_PER_MESSAGE = 5


class APIClient:
    """Authenticated HTTP client for the Donna API."""

    def __init__(self) -> None:
        self._base_url = settings.api_url.rstrip("/")
        self._headers = {
            "X-API-Key": settings.api_key,
            "Content-Type": "application/json",
        }

    async def call(self, endpoint: str, payload: dict | None = None) -> dict:
        """Make an authenticated POST request to the API.

        Args:
            endpoint: API path (e.g., "/calendar/list_events")
            payload: Request body as dict

        Returns:
            Response JSON as dict

        Raises:
            httpx.HTTPStatusError: On non-2xx responses
        """
        url = f"{self._base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload or {},
                headers=self._headers,
            )
            response.raise_for_status()
            result = response.json()

        logger.info(
            "api_call",
            endpoint=endpoint,
            success=result.get("success", False),
        )
        return result


api_client = APIClient()
