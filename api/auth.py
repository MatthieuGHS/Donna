"""API key authentication for FastAPI endpoints."""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Verify the API key from the X-API-Key header.

    Uses constant-time comparison to prevent timing attacks.
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    # Constant-time comparison to prevent timing attacks
    import hmac
    if not hmac.compare_digest(api_key.encode(), settings.api_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
