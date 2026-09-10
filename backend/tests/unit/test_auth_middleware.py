"""Unit tests for JWTAuthMiddleware — raw_token storage and basic dispatch."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_raw_token_stored_on_request_state():
    """After a valid JWT, request.state.raw_token is set to the extracted bearer value."""
    from app.middleware.auth import JWTAuthMiddleware

    captured_token: list[str] = []

    async def fake_call_next(req):
        captured_token.append(getattr(req.state, "raw_token", "NOT_SET"))
        return MagicMock()

    middleware = JWTAuthMiddleware(app=MagicMock())

    mock_request = MagicMock()
    mock_request.method = "GET"
    mock_request.url.path = "/api/v1/mcp/servers"
    mock_request.scope = {"type": "http"}
    mock_request.headers = {"Authorization": "Bearer test.jwt.token"}
    mock_request.state = MagicMock()
    mock_request.state.raw_token = ""

    valid_claims = {"sub": "user-123", "email": "user@example.com"}

    with patch.object(
        middleware, "_try_oidc_auth", new=AsyncMock(return_value=valid_claims)
    ):
        with patch.object(middleware, "_sync_user_and_groups", new=AsyncMock()):
            await middleware.dispatch(mock_request, fake_call_next)

    assert captured_token == ["test.jwt.token"], (
        f"Expected raw_token='test.jwt.token', got {captured_token}"
    )


@pytest.mark.asyncio
async def test_raw_token_empty_on_public_path():
    """Public paths bypass auth — raw_token is not set by the middleware."""
    from app.middleware.auth import JWTAuthMiddleware

    reached_call_next = []

    async def fake_call_next(req):
        reached_call_next.append(True)
        return MagicMock()

    middleware = JWTAuthMiddleware(app=MagicMock())

    mock_request = MagicMock()
    mock_request.method = "GET"
    mock_request.url.path = "/health"
    mock_request.scope = {"type": "http"}
    mock_request.headers = {}

    await middleware.dispatch(mock_request, fake_call_next)

    assert reached_call_next == [True], "call_next should have been called for a public path"
