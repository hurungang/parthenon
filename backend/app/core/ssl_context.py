"""Global SSL context for HTTPS requests using truststore.

Loads corporate CA certificates from the OS certificate store (Windows cert manager)
to avoid SSL verification errors when connecting to enterprise APIs.

Usage:
    from app.core.ssl_context import get_ssl_context
    
    async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
        response = await client.get("https://api.example.com")
"""
import ssl
import logging

logger = logging.getLogger(__name__)

# Global SSL context — initialized once
_ssl_context: ssl.SSLContext | None = None
_initialized = False


def get_ssl_context() -> ssl.SSLContext | bool:
    """Get the global SSL context for HTTPS requests.
    
    Returns:
        ssl.SSLContext if truststore is available and corporate certs are loaded,
        otherwise True (use default verification).
    """
    global _ssl_context, _initialized
    
    if not _initialized:
        try:
            import truststore
            _ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            logger.info("SSL context initialized with truststore (corporate CA certificates)")
        except ImportError:
            logger.warning(
                "truststore not available — using default SSL verification. "
                "Install truststore for corporate CA support: pip install truststore"
            )
            _ssl_context = None
        except Exception as exc:
            logger.warning("Failed to initialize SSL context with truststore: %s", exc)
            _ssl_context = None
        finally:
            _initialized = True
    
    return _ssl_context if _ssl_context is not None else True
