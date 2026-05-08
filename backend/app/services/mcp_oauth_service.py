"""MCP OAuth auto-discovery and dynamic client registration service.

Implements a triple-discovery pattern for MCP server OAuth configuration:
  1. WWW-Authenticate header (RFC 9728 resource metadata)
  2. /.well-known/oauth-authorization-server endpoint (RFC 8414)
  3. /oauth/metadata endpoint (MCP-specific)

Supports Dynamic Client Registration (DCR, RFC 7591) when no client_id is found.
"""

import json
import logging
import os
import re
import secrets
import ssl
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.mcp_oauth import OAuthDiscoveryResult

logger = logging.getLogger(__name__)

# Load corporate CA from OS certificate store via truststore (Windows cert manager)
try:
    import truststore
    _ssl_context: ssl.SSLContext | None = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except ImportError:
    _ssl_context = None

_MCP_OAUTH_REDIRECT_URI_DEFAULT = "http://localhost:5173/oauth/callback"
_DCR_CLIENT_NAME = "Parthenon MCP Hub"
_STATE_TTL_MINUTES = 15

# In-memory state storage for OAuth flows (shared with mcp_hub.py callback handler)
# In production, migrate this to Redis or a database table.
mcp_oauth_states: dict[str, dict] = {}


async def fetch_oauth_metadata(metadata_url: str, redirect_uri: str) -> OAuthDiscoveryResult:
    """Fetch OAuth configuration from a metadata document URL.
    
    Supports standard OAuth 2.0 metadata formats:
    - RFC 8414 (OAuth 2.0 Authorization Server Metadata)
    - OpenID Connect Discovery
    
    Args:
        metadata_url: URL to the OAuth metadata document.
        redirect_uri: OAuth redirect URI to embed in the result.
    
    Returns:
        OAuthDiscoveryResult with discovered endpoints.
    
    Raises:
        ValueError: When metadata cannot be fetched or parsed.
    """
    # Check if SSL verification should be disabled (for dev/testing)
    verify_ssl = os.getenv("MCP_OAUTH_VERIFY_SSL", "true").lower() != "false"
    # Use truststore SSL context (loads corporate CA from OS cert store) when SSL is enabled
    ssl_verify = (_ssl_context if _ssl_context is not None else True) if verify_ssl else False

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=ssl_verify) as client:
            logger.debug("Fetching OAuth metadata from %s", metadata_url)
            response = await client.get(metadata_url)
            response.raise_for_status()
            data = response.json()
            
            logger.debug("OAuth metadata fetched successfully")
            scopes = data.get("scopes_supported")
            scope_str: str | None = (
                " ".join(scopes) if isinstance(scopes, list) else scopes
            ) or data.get("scope")
            
            # Extract required fields
            auth_url = data.get("authorization_endpoint")
            token_url = data.get("token_endpoint")
            
            if not auth_url or not token_url:
                raise ValueError(
                    f"Metadata document at {metadata_url} missing required endpoints. "
                    f"Found: authorization_endpoint={auth_url}, token_endpoint={token_url}"
                )
            
            return OAuthDiscoveryResult(
                authorization_url=auth_url,
                token_url=token_url,
                client_id=data.get("client_id", ""),
                scope=scope_str,
                redirect_uri=redirect_uri,
                registration_endpoint=data.get("registration_endpoint"),
            )
    except httpx.ConnectError as exc:
        error_msg = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in error_msg or "SSL" in error_msg:
            raise ValueError(
                f"SSL certificate verification failed for {metadata_url}: {exc}. "
                "For development/testing only, you can set MCP_OAUTH_VERIFY_SSL=false to disable verification."
            )
        raise ValueError(
            f"Failed to connect to OAuth metadata URL {metadata_url}: {exc}"
        )
    except httpx.HTTPError as exc:
        raise ValueError(
            f"Failed to fetch OAuth metadata from {metadata_url}: {exc}"
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"Failed to parse OAuth metadata from {metadata_url}: {exc}"
        )


async def discover_oauth_config(mcp_base_url: str, redirect_uri: str) -> OAuthDiscoveryResult:
    """Auto-discover OAuth configuration from an MCP server.

    Tries in order:
    1. WWW-Authenticate header from a 401 response
    2. /.well-known/oauth-authorization-server
    3. /oauth/metadata

    Args:
        mcp_base_url: Base URL of the MCP server.
        redirect_uri: OAuth redirect URI to embed in the result.

    Returns:
        OAuthDiscoveryResult with discovered endpoints.

    Raises:
        ValueError: When none of the discovery methods succeed.
    """
    base = mcp_base_url.rstrip("/")
    # Method 1 probes the MCP protocol endpoint to trigger a 401 + WWW-Authenticate.
    # Convention: base_url stores the server root (e.g. https://mcp.supabase.com);
    # the MCP protocol path is /mcp. Guard against base_url values that already
    # include /mcp to avoid double-appending.
    mcp_endpoint = base if base.endswith("/mcp") else f"{base}/mcp"

    # Check if SSL verification should be disabled (for dev/testing)
    # WARNING: Never disable SSL verification in production!
    verify_ssl = os.getenv("MCP_OAUTH_VERIFY_SSL", "true").lower() != "false"
    if not verify_ssl:
        logger.warning("SSL verification disabled for MCP OAuth discovery (MCP_OAUTH_VERIFY_SSL=false)")
    # Use truststore SSL context (loads corporate CA from OS cert store) when SSL is enabled
    ssl_verify = (_ssl_context if _ssl_context is not None else True) if verify_ssl else False

    errors: list[str] = []  # Collect all errors for better diagnostics

    async with httpx.AsyncClient(timeout=10.0, verify=ssl_verify) as client:
        # ── Method 1: WWW-Authenticate header ─────────────────────────────────
        try:
            logger.debug("OAuth discovery method 1: WWW-Authenticate at %s", mcp_endpoint)
            response = await client.get(mcp_endpoint)
            if response.status_code == 401:
                www_auth = response.headers.get("WWW-Authenticate", "")
                logger.debug("WWW-Authenticate header: %s", www_auth)
                if www_auth:
                    result = await _parse_www_authenticate(www_auth, redirect_uri, client)
                    if result:
                        logger.info("OAuth discovered via WWW-Authenticate")
                        return result
        except httpx.ConnectError as exc:
            error_msg = f"WWW-Authenticate: Connection error - {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)
        except Exception as exc:
            error_msg = f"WWW-Authenticate: {type(exc).__name__} - {exc}"
            logger.debug(error_msg)
            errors.append(error_msg)

        # ── Method 2: /.well-known/oauth-authorization-server ─────────────────
        well_known_url = f"{base}/.well-known/oauth-authorization-server"
        try:
            logger.debug("OAuth discovery method 2: %s", well_known_url)
            response = await client.get(well_known_url)
            if response.status_code == 200:
                data = response.json()
                logger.info("OAuth discovered via well-known endpoint")
                scopes = data.get("scopes_supported")
                scope_str: str | None = (
                    " ".join(scopes) if isinstance(scopes, list) else scopes
                ) or data.get("scope")
                return OAuthDiscoveryResult(
                    authorization_url=data.get("authorization_endpoint", ""),
                    token_url=data.get("token_endpoint", ""),
                    client_id=data.get("client_id", ""),
                    scope=scope_str,
                    redirect_uri=redirect_uri,
                    registration_endpoint=data.get("registration_endpoint"),
                )
        except httpx.ConnectError as exc:
            error_msg = f"Well-known: Connection error - {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)
        except Exception as exc:
            error_msg = f"Well-known: {type(exc).__name__} - {exc}"
            logger.debug(error_msg)
            errors.append(error_msg)

        # ── Method 3: /oauth/metadata ──────────────────────────────────────────
        oauth_meta_url = f"{base}/oauth/metadata"
        try:
            logger.debug("OAuth discovery method 3: %s", oauth_meta_url)
            response = await client.get(oauth_meta_url)
            if response.status_code == 200:
                data = response.json()
                logger.info("OAuth discovered via MCP metadata endpoint")
                return OAuthDiscoveryResult(
                    authorization_url=data.get("authorization_url", ""),
                    token_url=data.get("token_url", ""),
                    client_id=data.get("client_id", ""),
                    scope=data.get("scope"),
                    redirect_uri=redirect_uri,
                    registration_endpoint=data.get("registration_endpoint"),
                )
        except httpx.ConnectError as exc:
            error_msg = f"MCP metadata: Connection error - {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)
        except Exception as exc:
            error_msg = f"MCP metadata: {type(exc).__name__} - {exc}"
            logger.debug(error_msg)
            errors.append(error_msg)

    # All methods failed - provide detailed error message
    error_details = "; ".join(errors) if errors else "All discovery methods returned no OAuth config"
    raise ValueError(
        f"Could not discover OAuth configuration from MCP server at {mcp_base_url}. "
        f"Errors: {error_details}. "
        "Tried WWW-Authenticate, /.well-known/oauth-authorization-server, and /oauth/metadata. "
        "If SSL certificate verification is failing, you can set MCP_OAUTH_VERIFY_SSL=false (dev only)."
    )


async def _parse_www_authenticate(
    www_auth_header: str,
    redirect_uri: str,
    client: httpx.AsyncClient,
) -> OAuthDiscoveryResult | None:
    """Parse a WWW-Authenticate header to extract OAuth endpoints.

    Supports:
    - resource_metadata="<url>" (RFC 9728 resource metadata → authorization server)
    - Bearer / OAuth realm with direct authorization_uri / token_uri params

    Returns None if the header cannot be parsed into a usable config.
    """
    try:
        params: dict[str, str] = {
            k.lower(): v
            for k, v in re.findall(r'(\w+)="([^"]*)"', www_auth_header)
        }
        logger.debug("WWW-Authenticate params: %s", params)

        resource_metadata_url = params.get("resource_metadata")
        if resource_metadata_url:
            logger.debug("Fetching resource_metadata from %s", resource_metadata_url)
            try:
                meta_resp = await client.get(resource_metadata_url)
                if meta_resp.status_code == 200:
                    metadata = meta_resp.json()

                    # Direct endpoints present in the resource metadata
                    if metadata.get("authorization_endpoint") and metadata.get("token_endpoint"):
                        scopes = metadata.get("scopes_supported")
                        scope_str: str | None = (
                            " ".join(scopes) if isinstance(scopes, list) else scopes
                        ) or metadata.get("scope")
                        return OAuthDiscoveryResult(
                            authorization_url=metadata["authorization_endpoint"],
                            token_url=metadata["token_endpoint"],
                            client_id=metadata.get("client_id", ""),
                            scope=scope_str,
                            redirect_uri=redirect_uri,
                            registration_endpoint=metadata.get("registration_endpoint"),
                        )

                    # RFC 8414: resolve via authorization_servers list
                    auth_servers: list[str] = metadata.get("authorization_servers", [])
                    if auth_servers:
                        as_base = auth_servers[0].rstrip("/")
                        as_url = f"{as_base}/.well-known/oauth-authorization-server"
                        as_resp = await client.get(as_url)
                        if as_resp.status_code == 200:
                            as_meta = as_resp.json()
                            res_scopes = metadata.get("scopes_supported")
                            scope_str = (
                                " ".join(res_scopes) if isinstance(res_scopes, list) else res_scopes
                            ) or as_meta.get("scope")
                            return OAuthDiscoveryResult(
                                authorization_url=as_meta.get("authorization_endpoint", ""),
                                token_url=as_meta.get("token_endpoint", ""),
                                client_id=as_meta.get("client_id") or metadata.get("client_id", ""),
                                scope=scope_str,
                                redirect_uri=redirect_uri,
                                registration_endpoint=as_meta.get("registration_endpoint"),
                            )
            except Exception as exc:
                logger.debug("resource_metadata fetch failed: %s", exc)

        # Fallback: direct params from header (Bearer realm pattern)
        authorization_url = (
            params.get("authorization_uri")
            or params.get("oauth_authorization_uri")
            or params.get("authorization_endpoint")
        )
        token_url = (
            params.get("token_uri")
            or params.get("oauth_token_uri")
            or params.get("token_endpoint", "")
        )
        if authorization_url:
            return OAuthDiscoveryResult(
                authorization_url=authorization_url,
                token_url=token_url,
                client_id=params.get("client_id", ""),
                scope=params.get("scope"),
                redirect_uri=redirect_uri,
                registration_endpoint=None,
            )
    except Exception as exc:
        logger.debug("WWW-Authenticate parse error: %s", exc)

    return None


async def register_dynamic_client(
    registration_endpoint: str,
    redirect_uri: str,
    client_name: str = _DCR_CLIENT_NAME,
) -> tuple[str, str | None]:
    """Register a dynamic OAuth client via RFC 7591.

    Args:
        registration_endpoint: URL of the OAuth server's registration endpoint.
        redirect_uri: Callback URI for the OAuth flow.
        client_name: Human-readable name for the registered client.

    Returns:
        (client_id, client_secret) – client_secret is None for public clients.

    Raises:
        ValueError: If registration fails.
    """
    request_body = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "application_type": "web",
    }
    logger.debug("DCR request to %s: %s", registration_endpoint, request_body)

    verify_ssl = os.getenv("MCP_OAUTH_VERIFY_SSL", "true").lower() != "false"
    ssl_verify = (_ssl_context if _ssl_context is not None else True) if verify_ssl else False

    async with httpx.AsyncClient(timeout=10.0, verify=ssl_verify) as http_client:
        response = await http_client.post(
            registration_endpoint,
            json=request_body,
            headers={"Content-Type": "application/json"},
        )
        logger.debug("DCR response status: %s", response.status_code)

        if response.status_code == 201:
            data = response.json()
            client_id: str | None = data.get("client_id")
            if not client_id:
                raise ValueError("Dynamic client registration succeeded but returned no client_id")
            logger.debug("DCR successful, client_id=%s", client_id)
            return (client_id, data.get("client_secret"))

        raise ValueError(
            f"Dynamic client registration failed (HTTP {response.status_code}): {response.text}"
        )


async def initiate_oauth_flow(
    server_id: UUID,
    db: AsyncSession,
    manual_config: OAuthDiscoveryResult | None = None,
    session_name: str | None = None,
    session_description: str | None = None,
) -> dict:
    """Auto-discover OAuth config and generate an authorization URL for an MCP server.

    Discovery order (if manual_config is not provided):
    1. Use server.oauth_config if it has authorization_url and client_id.
    2. Auto-discover from server.base_url using the triple-discovery pattern.
    3. Perform DCR if a registration_endpoint is available but no client_id.

    If manual_config is provided, uses it directly and skips auto-discovery.

    Stores OAuth state in the module-level ``mcp_oauth_states`` dict for the
    callback handler to consume.

    Args:
        server_id: UUID of the McpServer to authorize.
        db: Async SQLAlchemy session.
        manual_config: Optional manual OAuth configuration to use instead of discovery.
        session_name: Optional user-provided name for the session to create.
        session_description: Optional user-provided description for the session.

    Returns:
        {"authorization_url": str}

    Raises:
        HTTPException 404: Server not found.
        HTTPException 400: Discovery or DCR failure.
    """
    from fastapi import HTTPException
    from app.db.models.mcp_hub import McpServer

    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    redirect_uri = os.getenv("MCP_OAUTH_REDIRECT_URI", _MCP_OAUTH_REDIRECT_URI_DEFAULT)

    # ── Use manual config if provided ──────────────────────────────────────────
    discovery_result: OAuthDiscoveryResult | None = manual_config
    
    # ── Use pre-configured oauth_config if complete ────────────────────────────
    if discovery_result is None and server.oauth_config:
        auth_url = server.oauth_config.get("authorization_url")
        client_id = server.oauth_config.get("client_id")
        if auth_url and client_id:
            logger.debug(
                "Using pre-configured oauth_config for server %s", server_id
            )
            discovery_result = OAuthDiscoveryResult(
                authorization_url=auth_url,
                token_url=server.oauth_config.get("token_url", ""),
                client_id=client_id,
                client_secret=server.oauth_config.get("client_secret"),
                scope=server.oauth_config.get("scope"),
                redirect_uri=server.oauth_config.get("redirect_uri", redirect_uri),
                registration_endpoint=server.oauth_config.get("registration_endpoint"),
            )

    # ── Auto-discover if no complete static config ─────────────────────────────
    if discovery_result is None:
        logger.debug("No complete oauth_config, starting auto-discovery for server %s", server_id)
        try:
            discovery_result = await discover_oauth_config(server.base_url, redirect_uri)
        except ValueError as exc:
            logger.warning("OAuth discovery failed for server %s: %s", server_id, exc)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not discover OAuth configuration from MCP server at {server.base_url}. "
                    f"Error: {str(exc)}. "
                    "You may need to manually provide the OAuth configuration (authorization_url, token_url, client_id)."
                ),
            )

    # ── DCR if no client_id ────────────────────────────────────────────────────
    if not discovery_result.client_id:
        if not discovery_result.registration_endpoint:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not discover OAuth configuration from MCP server: "
                    "no client_id found and no Dynamic Client Registration endpoint available."
                ),
            )
        logger.debug(
            "No client_id; attempting DCR at %s", discovery_result.registration_endpoint
        )
        try:
            dyn_client_id, dyn_client_secret = await register_dynamic_client(
                registration_endpoint=discovery_result.registration_endpoint,
                redirect_uri=redirect_uri,
            )
        except (ValueError, httpx.ConnectError, httpx.HTTPError) as exc:
            logger.error("DCR failed for server %s: %s", server_id, exc)
            raise HTTPException(
                status_code=400,
                detail=f"Dynamic client registration failed: {exc}",
            )
        discovery_result.client_id = dyn_client_id
        if dyn_client_secret:
            discovery_result.client_secret = dyn_client_secret

    # ── Store state and build authorization URL ────────────────────────────────
    state = secrets.token_urlsafe(32)
    mcp_oauth_states[state] = {
        "server_id": str(server_id),
        "client_id": discovery_result.client_id,
        "client_secret": discovery_result.client_secret,
        "token_url": discovery_result.token_url,
        "redirect_uri": redirect_uri,
        "session_name": session_name,
        "session_description": session_description,
        "expires_at": (
            datetime.now(tz=timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES)
        ).isoformat(),
    }

    params: dict[str, str] = {
        "client_id": discovery_result.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if discovery_result.scope:
        params["scope"] = discovery_result.scope

    authorization_url = f"{discovery_result.authorization_url}?{urlencode(params)}"
    logger.debug(
        "OAuth flow initiated for server %s: client_id=%s",
        server_id,
        discovery_result.client_id,
    )
    return {"authorization_url": authorization_url}


async def _initialize_mcp_session(base_url: str, access_token: str) -> str:
    """Initialize an MCP session with the server and get the session ID.
    
    After OAuth authentication, some MCP servers require an initialization handshake
    to establish a session. This function attempts to call the initialize endpoint.
    If initialization is not supported or fails, generates a UUID instead.
    
    Args:
        base_url: Base URL of the MCP server
        access_token: OAuth access token for authentication
        
    Returns:
        MCP session ID string
    """
    endpoint = base_url.rstrip("/")
    
    # MCP protocol initialize payload
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "Parthenon MCP Hub",
                "version": "1.0.0"
            }
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {access_token}"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context or True) as client:
            logger.debug("Initializing MCP session at %s", endpoint)
            logger.debug("MCP initialize payload: %s", json.dumps(payload))
            response = await client.post(endpoint, json=payload, headers=headers)
            
            logger.debug("MCP initialize response status: %d", response.status_code)
            logger.debug("MCP initialize response headers: %s", dict(response.headers))
            
            response.raise_for_status()
            
            result = response.json()
            logger.debug("MCP initialize response: %s", result)
            
            # Extract session ID from response headers (Supabase MCP pattern)
            mcp_session_id = response.headers.get("Mcp-Session-Id")
            
            if not mcp_session_id:
                # Try to extract from response body if not in headers
                if isinstance(result, dict):
                    mcp_session_id = result.get("sessionId") or result.get("session_id")
            
            if not mcp_session_id:
                logger.warning("MCP server did not return session ID, using generated UUID")
                import uuid
                mcp_session_id = str(uuid.uuid4())
            
            logger.info("MCP session initialized with ID: %s", mcp_session_id[:16] + "...")
            return mcp_session_id
            
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "MCP initialize endpoint returned HTTP %d (this may be expected for some servers): %s",
            exc.response.status_code,
            exc.response.text[:200]
        )
        # Generate a UUID since initialize is not supported or failed
        import uuid
        generated_id = str(uuid.uuid4())
        logger.info("Generated MCP session ID (initialize not supported): %s", generated_id[:16] + "...")
        return generated_id
    except httpx.HTTPError as exc:
        logger.warning("MCP initialize failed (network error): %s", exc)
        # Generate a UUID as fallback
        import uuid
        generated_id = str(uuid.uuid4())
        logger.info("Generated MCP session ID (network error): %s", generated_id[:16] + "...")
        return generated_id


async def handle_oauth_callback(
    code: str,
    state: str,
    db: AsyncSession,
) -> dict:
    """Exchange authorization code for access token and create an MCP session.

    Steps:
    1. Retrieve and validate state from ``mcp_oauth_states`` (includes expiration check).
    2. Exchange code for access token via POST to the stored token_url.
    3. Encrypt acquired tokens via CredentialVault.
    4. Create an MCP session with auth_type='oauth2' and encrypted credentials.
    5. Clean up the consumed state to prevent replay attacks.

    Args:
        code: Authorization code returned by the OAuth provider.
        state: State token from the OAuth redirect; must match a pending flow.
        db: Async SQLAlchemy session.

    Returns:
        {"success": True, "session_id": str, "message": str}

    Raises:
        HTTPException 400: Invalid/expired state or token exchange failure.
        HTTPException 500: Session creation failure.
    """
    import json
    from fastapi import HTTPException
    from app.db.models.mcp_hub import McpSession, McpSessionAuthType
    from app.core.credential_vault import get_vault

    # ── 1. Validate state ──────────────────────────────────────────────────────
    state_data = mcp_oauth_states.get(state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    expires_at_str: str | None = state_data.get("expires_at")
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now(tz=timezone.utc) > expires_at:
                mcp_oauth_states.pop(state, None)
                raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
        except (ValueError, TypeError):
            pass  # Malformed timestamp — don't block; proceed

    server_id_str: str = state_data["server_id"]
    client_id: str = state_data["client_id"]
    client_secret: str | None = state_data.get("client_secret")
    token_url: str = state_data["token_url"]
    redirect_uri: str = state_data["redirect_uri"]

    # ── 2. Exchange code for tokens ────────────────────────────────────────────
    token_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }
    if client_secret:
        token_data["client_secret"] = client_secret

    # Use truststore for corporate cert handling
    verify_ssl = os.getenv("MCP_OAUTH_VERIFY_SSL", "true").lower() != "false"
    ssl_verify: httpx._client.VerifyTypes = True
    try:
        import truststore
        ssl_verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        logger.debug("Using truststore for token exchange SSL verification")
    except Exception:
        logger.debug("truststore not available for token exchange, using default SSL verification")

    if not verify_ssl:
        ssl_verify = False
        logger.warning("SSL verification disabled for token exchange (dev only)")

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=ssl_verify) as http_client:
            response = await http_client.post(
                token_url,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            # Accept any 2xx status code (200 OK, 201 Created, etc.)
            if not (200 <= response.status_code < 300):
                logger.error(
                    "OAuth token exchange failed for server %s: HTTP %s — %s",
                    server_id_str,
                    response.status_code,
                    response.text,
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Token exchange failed: {response.text}",
                )
            tokens: dict = response.json()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OAuth token exchange error for server %s: %s", server_id_str, exc)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    # Extract access token from response for immediate use
    access_token = tokens.get("access_token")
    if not access_token:
        logger.error("OAuth token response missing access_token for server %s", server_id_str)
        raise HTTPException(status_code=400, detail="Token response missing access_token")

    # ── 3. Encrypt credentials ─────────────────────────────────────────────────
    vault = get_vault()
    credentials_json = json.dumps({
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token"),
        "expires_in": tokens.get("expires_in"),
    })
    encrypted_creds = vault.encrypt(credentials_json)

    # Calculate token expiry timestamps
    now = datetime.now(tz=timezone.utc)
    expires_in = tokens.get("expires_in")  # seconds until access token expires
    refresh_expires_in = tokens.get("refresh_expires_in")  # seconds until refresh token expires
    
    oauth_expires_at = None
    if expires_in:
        try:
            oauth_expires_at = now + timedelta(seconds=int(expires_in))
        except (ValueError, TypeError):
            logger.warning("Invalid expires_in value: %s", expires_in)
    
    oauth_refresh_expires_at = None
    if refresh_expires_in:
        try:
            oauth_refresh_expires_at = now + timedelta(seconds=int(refresh_expires_in))
        except (ValueError, TypeError):
            logger.warning("Invalid refresh_expires_in value: %s", refresh_expires_in)
    
    # Store OAuth metadata for token refresh (need token_url and client credentials)
    oauth_metadata = {
        "token_url": token_url,
        "client_id": client_id,
    }
    if client_secret:
        oauth_metadata["client_secret"] = client_secret

    # ── 4. Get server to initialize MCP session ────────────────────────────────
    from app.db.models.mcp_hub import McpServer
    from sqlalchemy import select
    
    server_result = await db.execute(select(McpServer).where(McpServer.id == UUID(server_id_str)))
    server = server_result.scalar_one_or_none()
    if not server:
        logger.error("Server %s not found for OAuth callback", server_id_str)
        raise HTTPException(status_code=404, detail="MCP server not found")

    # ── 5. Initialize MCP session with server and get session ID ───────────────
    # Use user-provided name from state, or generate a default name
    state_data = mcp_oauth_states.get(state, {})
    user_provided_name = state_data.get("session_name")
    user_provided_desc = state_data.get("session_description")
    
    session_name = user_provided_name or f"OAuth Session {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    session_description = user_provided_desc or "Created via OAuth flow"
    
    # Initialize MCP session with the server to get MCP session ID
    mcp_session_id = await _initialize_mcp_session(server.base_url, access_token)
    
    # Store MCP session ID in identity_binding
    identity_binding = {
        "mcp_session_id": mcp_session_id
    }
    
    # ── 6. Create database session record ──────────────────────────────────────
    session = McpSession(
        server_id=UUID(server_id_str),
        name=session_name,
        description=session_description,
        auth_type=McpSessionAuthType.oauth2,
        encrypted_credentials=encrypted_creds,
        oauth_expires_at=oauth_expires_at,
        oauth_refresh_expires_at=oauth_refresh_expires_at,
        oauth_metadata=oauth_metadata,
        identity_binding=identity_binding,
    )
    try:
        db.add(session)
        await db.flush()
        await db.refresh(session)
    except Exception as exc:
        logger.error("Failed to create MCP session for server %s: %s", server_id_str, exc)
        raise HTTPException(status_code=500, detail="Failed to create MCP session")

    # ── 7. Automatically sync tools from server ────────────────────────────────
    from app.services.mcp.tool_sync import ToolSyncService
    
    sync_result = {"added": 0, "updated": 0, "deactivated": 0}
    try:
        logger.info(f"Automatically syncing tools for server {server_id_str} after OAuth success")
        sync_service = ToolSyncService()
        sync_result = await sync_service.sync(server, db, session=session)
        logger.info(f"Tool sync completed: {sync_result}")
    except Exception as sync_exc:
        # Log error but don't fail the OAuth flow
        logger.warning(f"Tool sync failed for server {server_id_str}: {sync_exc}")

    # ── 8. Clean up state (prevent replay) ────────────────────────────────────
    mcp_oauth_states.pop(state, None)

    logger.info(
        "Created OAuth MCP session %s for server %s with %d tools synced", 
        session.id, server_id_str, sync_result.get("added", 0) + sync_result.get("updated", 0)
    )
    return {
        "success": True,
        "session_id": str(session.id),
        "message": "OAuth authentication successful",
        "tools_synced": sync_result,
    }
