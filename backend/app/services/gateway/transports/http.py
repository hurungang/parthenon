"""HTTP Gateway Transport adapter."""

from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler


class HttpGatewayTransport:
    """
    HTTP adapter that marshals inbound HTTP requests to GatewayLifecycleHandler
    and serializes structured responses.

    The actual HTTP endpoints are defined in app.api.gateway.lifecycle.
    This class is the logical boundary between transport and handler.
    """

    def __init__(self) -> None:
        self._handler = GatewayLifecycleHandler()

    @property
    def handler(self) -> GatewayLifecycleHandler:
        """Return the underlying lifecycle handler."""
        return self._handler
