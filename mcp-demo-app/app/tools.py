from __future__ import annotations

from typing import Any, Callable

from app.booking_store import BookingError, booking_store


def _error_result(message: str) -> dict[str, Any]:
    """Structured error result shape used by all booking tools."""
    return {"error": True, "message": message}


def _require_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def hello_world_tool(agent_identity: dict[str, Any]) -> dict[str, Any]:
    """Return a greeting that surfaces the caller's agent identity."""
    return {
        "message": "Hello from MCP Demo App!",
        "agent_sub": agent_identity.get("sub"),
        "agent_claims": agent_identity,
    }


def hello_agent_tool(agent_identity: dict[str, Any]) -> dict[str, Any]:
    """Greets the calling agent identity. Requires mcp_role 'demo_agent'."""
    mcp_role = agent_identity.get("mcp_role")
    if mcp_role != "demo_agent":
        return {"access_denied": True, "reason": "Agent identity lacks required mcp_role: demo_agent"}
    return {
        "message": "Hello Agent!",
        "agent_sub": agent_identity.get("sub"),
        "agent_realm": agent_identity.get("iss"),
        "agent_mcp_role": agent_identity.get("mcp_role"),
        "agent_claims": agent_identity,
    }


def hello_user_tool(user_identity: dict[str, Any]) -> dict[str, Any]:
    """Greets the calling user identity. Requires mcp_role 'demo_user'."""
    mcp_role = user_identity.get("mcp_role")
    if mcp_role != "demo_user":
        return {"access_denied": True, "reason": "User identity lacks required mcp_role: demo_user"}
    return {
        "message": "Hello User!",
        "user_sub": user_identity.get("sub"),
        "user_realm": user_identity.get("iss"),
        "user_mcp_role": user_identity.get("mcp_role"),
        "user_claims": user_identity,
    }


# ── Airline booking tools (scenario demo — fictional in-memory data) ─────────


def search_flights_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Search seed flights by origin, destination, and date (read-only)."""
    origin = _require_str(arguments, "origin")
    destination = _require_str(arguments, "destination")
    date = _require_str(arguments, "date")
    missing = [k for k, v in (("origin", origin), ("destination", destination), ("date", date)) if v is None]
    if missing:
        return _error_result(f"Missing required argument(s): {', '.join(missing)}")
    flights = booking_store.search_flights(origin, destination, date)
    return {
        "search": {"origin": origin, "destination": destination, "date": date},
        "results": flights,
        "count": len(flights),
    }


def book_ticket_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a booking for one or more passengers (returns its PNR).
    Confirm-before-write gating is applied platform-side."""
    flight_id = _require_str(arguments, "flight_id")
    passengers = arguments.get("passengers")
    missing = [k for k, v in (("flight_id", flight_id), ("passengers", passengers)) if v is None]
    if missing:
        return _error_result(f"Missing required argument(s): {', '.join(missing)}")
    if not isinstance(passengers, list):
        return _error_result("'passengers' must be a list of passenger objects (name, type, bags)")
    try:
        booking = booking_store.create_booking(flight_id, passengers, booked_by=agent_identity.get("sub"))
    except BookingError as exc:
        return _error_result(str(exc))
    names = ", ".join(p["name"] for p in booking["passengers"])
    return {"message": f"Booking confirmed (PNR {booking['pnr']}) for {names}", "booking": booking}


def generate_payment_link_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Generate a fictional payment link for an existing booked booking."""
    pnr = _require_str(arguments, "pnr")
    if pnr is None:
        return _error_result("Missing required argument(s): pnr")
    try:
        link = booking_store.generate_payment_link(pnr)
    except BookingError as exc:
        return _error_result(str(exc))
    return {"message": "Payment link generated (simulated payment completed)", "payment": link}


def check_ticket_status_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Return current status plus flight/passenger details for a PNR (read-only)."""
    pnr = _require_str(arguments, "pnr")
    if pnr is None:
        return _error_result("Missing required argument(s): pnr")
    try:
        booking = booking_store.get_booking(pnr)
    except BookingError as exc:
        return _error_result(str(exc))
    return {"booking": booking}


def check_in_passenger_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Check in a paid booking via PNR (paid → checked-in); all passengers on
    the booking are checked in with it."""
    pnr = _require_str(arguments, "pnr")
    if pnr is None:
        return _error_result("Missing required argument(s): pnr")
    try:
        booking = booking_store.check_in(pnr)
    except BookingError as exc:
        return _error_result(str(exc))
    names = ", ".join(p["name"] for p in booking["passengers"])
    return {"message": f"Passengers {names} are checked in", "booking": booking}


def select_seat_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Assign a seat to one passenger of a checked-in booking (PNR + passenger + seat)."""
    pnr = _require_str(arguments, "pnr")
    passenger = _require_str(arguments, "passenger")
    seat = _require_str(arguments, "seat")
    missing = [
        k for k, v in (("pnr", pnr), ("passenger", passenger), ("seat", seat)) if v is None
    ]
    if missing:
        return _error_result(f"Missing required argument(s): {', '.join(missing)}")
    try:
        booking = booking_store.select_seat(pnr, passenger, seat)  # type: ignore[arg-type]
    except BookingError as exc:
        return _error_result(str(exc))
    return {"message": f"Seat {seat} assigned to {passenger}", "booking": booking}


def cancel_booking_tool(agent_identity: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Cancel a booking (destructive; confirm-before-write gated platform-side).
    Frees the seats of all passengers on the booking."""
    pnr = _require_str(arguments, "pnr")
    if pnr is None:
        return _error_result("Missing required argument(s): pnr")
    try:
        booking = booking_store.cancel(pnr)
    except BookingError as exc:
        return _error_result(str(exc))
    return {"message": f"Booking {booking['pnr']} cancelled; all seats freed", "booking": booking}


tool_registry: dict[str, Callable[..., dict[str, Any]]] = {
    "helloWorld": hello_world_tool,
    "helloAgent": hello_agent_tool,
    "helloUser": hello_user_tool,
    "searchFlights": search_flights_tool,
    "bookTicket": book_ticket_tool,
    "generatePaymentLink": generate_payment_link_tool,
    "checkTicketStatus": check_ticket_status_tool,
    "checkInPassenger": check_in_passenger_tool,
    "selectSeat": select_seat_tool,
    "cancelBooking": cancel_booking_tool,
}

# Booking tools take an ``arguments`` dict in addition to the caller identity.
BOOKING_TOOL_NAMES: set[str] = {
    "searchFlights",
    "bookTicket",
    "generatePaymentLink",
    "checkTicketStatus",
    "checkInPassenger",
    "selectSeat",
    "cancelBooking",
}

TOOL_MANIFEST: list[dict[str, Any]] = [
    {
        "name": "helloWorld",
        "description": (
            "Returns a greeting message that includes the calling agent's "
            "identity (sub claim) from the forwarded JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "helloAgent",
        "description": (
            "Greets the calling agent identity. "
            "Requires the agent to have mcp_role 'demo_agent'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "helloUser",
        "description": (
            "Greets the calling user identity. "
            "Requires the user to have mcp_role 'demo_user'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "searchFlights",
        "description": (
            "Search fictional airline flights by origin, destination, and date. "
            "Returns flight number, times, fare, and seats available. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Origin city, e.g. 'Aurora City'"},
                "destination": {"type": "string", "description": "Destination city, e.g. 'Meridian Falls'"},
                "date": {"type": "string", "description": "Travel date, e.g. '2030-03-15'"},
            },
            "required": ["origin", "destination", "date"],
        },
    },
    {
        "name": "bookTicket",
        "description": (
            "Book a flight for one or more passengers (confirm-before-write: "
            "the platform approval flow precedes every invocation). Returns "
            "the booking PNR with status 'booked'; one seat is reserved per "
            "passenger. A child or infant cannot travel without at least one "
            "adult on the same booking."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "flight_id": {"type": "string", "description": "Flight identifier, e.g. 'FL-101'"},
                "passengers": {
                    "type": "array",
                    "description": "Passengers on this booking (at least one)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Passenger full name"},
                            "type": {
                                "type": "string",
                                "enum": ["adult", "child", "infant"],
                                "description": "Passenger type (default adult)",
                            },
                            "bags": {
                                "type": "integer",
                                "description": "Bag count for this passenger (default 0)",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["flight_id", "passengers"],
        },
    },
    {
        "name": "generatePaymentLink",
        "description": (
            "Generate a fictional payment link for an existing booking in "
            "'booked' state. The demo simulates payment success: the booking "
            "becomes 'paid' (amount = fare × passenger count). No real money "
            "movement."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pnr": {"type": "string", "description": "Booking PNR, e.g. 'PKT001'"},
            },
            "required": ["pnr"],
        },
    },
    {
        "name": "checkTicketStatus",
        "description": (
            "Return the current booking status (booked / paid / checked-in / "
            "cancelled) plus flight and per-passenger seat details. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pnr": {"type": "string", "description": "Booking PNR, e.g. 'PKT001'"},
            },
            "required": ["pnr"],
        },
    },
    {
        "name": "checkInPassenger",
        "description": (
            "Check in a booking by PNR. Allowed only for paid bookings; "
            "transitions the booking (and all its passengers) to 'checked-in'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pnr": {"type": "string", "description": "Booking PNR, e.g. 'PKT001'"},
            },
            "required": ["pnr"],
        },
    },
    {
        "name": "selectSeat",
        "description": (
            "Select a seat for one passenger of a checked-in booking. "
            "Validates that the passenger is on the booking, the seat exists "
            "and is free; marks it occupied and attaches it to the passenger."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pnr": {"type": "string", "description": "Booking PNR, e.g. 'PKT001'"},
                "passenger": {"type": "string", "description": "Passenger name on this booking"},
                "seat": {"type": "string", "description": "Seat identifier, e.g. '1A' (rows 1-4, seats A-F)"},
            },
            "required": ["pnr", "passenger", "seat"],
        },
    },
    {
        "name": "cancelBooking",
        "description": (
            "Cancel a booking by PNR (destructive, confirm-before-write "
            "gated platform-side). Frees the seats of all passengers on the "
            "booking so they become re-bookable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pnr": {"type": "string", "description": "Booking PNR, e.g. 'PKT001'"},
            },
            "required": ["pnr"],
        },
    },
]
