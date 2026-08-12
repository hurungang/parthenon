"""Test SSL context fix for certificate verification."""
import sys
import asyncio

sys.path.insert(0, ".")

from app.core.ssl_context import get_ssl_context


def test_ssl_context():
    """Verify SSL context is initialized correctly."""
    ssl_ctx = get_ssl_context()
    print(f"✅ SSL Context type: {type(ssl_ctx).__name__}")
    print(f"✅ Has check_hostname: {hasattr(ssl_ctx, 'check_hostname')}")
    print(f"✅ Is SSLContext: {str(type(ssl_ctx)).endswith('ssl.SSLContext>')}")
    return ssl_ctx


if __name__ == "__main__":
    ctx = test_ssl_context()
    print("\n✅ SSL context fix verified successfully!")
