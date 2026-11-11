"""Unit tests for the seven booking tool handlers in app/tools.py.

Happy paths plus invalid references, wrong-state transitions, the
child/infant-without-adult rule, multi-passenger bookings, bags,
per-passenger seat selection, cancel-and-rebook, and error-shape
consistency with the existing greeting tools.
"""
from __future__ import annotations

import pytest

from app.booking_store import SEED_TRAVEL_DATE, BookingStore
from app.tools import (
    BOOKING_TOOL_NAMES,
    TOOL_MANIFEST,
    book_ticket_tool,
    cancel_booking_tool,
    check_in_passenger_tool,
    check_ticket_status_tool,
    generate_payment_link_tool,
    search_flights_tool,
    select_seat_tool,
    tool_registry,
)

_IDENTITY = {"sub": "agent-abc", "iss": "http://kc/realms/ai_agents", "mcp_role": "demo_agent"}


def _pax(name: str, pax_type: str = "adult", bags: int = 0) -> dict:
    return {"name": name, "type": pax_type, "bags": bags}


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """Give every test a pristine store (handlers use the module singleton)."""
    from app import booking_store as bs_module
    from app import tools as tools_module

    store = BookingStore()
    monkeypatch.setattr(bs_module, "booking_store", store)
    monkeypatch.setattr(tools_module, "booking_store", store)
    return store


# ── searchFlights ────────────────────────────────────────────────────────────


def test_search_flights_happy_path():
    result = search_flights_tool(_IDENTITY, {
        "origin": "Aurora City", "destination": "Meridian Falls", "date": SEED_TRAVEL_DATE,
    })
    assert "error" not in result
    assert result["count"] == 3
    assert result["results"][0]["flight_id"].startswith("FL-1")


def test_search_flights_arbitrary_route_not_error_and_bookable():
    result = search_flights_tool(_IDENTITY, {
        "origin": "Port Lumina", "destination": "Vega Hollow", "date": "2031-07-04",
    })
    assert "error" not in result
    assert 3 <= result["count"] <= 5
    assert all(f["seats_available"] == f["seats_total"] for f in result["results"])


def test_search_flights_generated_flights_deterministic():
    args = {"origin": "Port Lumina", "destination": "Vega Hollow", "date": "2031-07-04"}
    r1 = search_flights_tool(_IDENTITY, args)
    r2 = search_flights_tool(_IDENTITY, args)
    assert [f["flight_id"] for f in r1["results"]] == [f["flight_id"] for f in r2["results"]]


def test_search_flights_generated_flight_full_tool_lifecycle():
    search = search_flights_tool(_IDENTITY, {
        "origin": "Port Lumina", "destination": "Vega Hollow", "date": "2031-07-04",
    })
    flight = search["results"][0]
    booked = book_ticket_tool(_IDENTITY, {
        "flight_id": flight["flight_id"],
        "passengers": [_pax("Jane Doe"), _pax("Timmy", "child", bags=1)],
    })
    assert "error" not in booked
    pnr = booked["booking"]["pnr"]
    paid = generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    assert paid["payment"]["amount"] == flight["fare"] * 2
    assert check_ticket_status_tool(_IDENTITY, {"pnr": pnr})["booking"]["status"] == "paid"
    checked_in = check_in_passenger_tool(_IDENTITY, {"pnr": pnr})
    assert checked_in["booking"]["status"] == "checked-in"
    seat = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Jane Doe", "seat": "4F"})
    assert seat["booking"]["passengers"][0]["seat"] == "4F"
    cancelled = cancel_booking_tool(_IDENTITY, {"pnr": pnr})
    assert cancelled["booking"]["status"] == "cancelled"
    rebooked = book_ticket_tool(_IDENTITY, {
        "flight_id": flight["flight_id"], "passengers": [_pax("Bob Ray")],
    })
    assert "error" not in rebooked


def test_search_flights_same_origin_destination_is_error():
    result = search_flights_tool(_IDENTITY, {
        "origin": "Aurora City", "destination": "aurora city", "date": SEED_TRAVEL_DATE,
    })
    assert result["error"] is True
    assert "different" in result["message"]


def test_manifest_search_flights_describes_dynamic_generation():
    entry = next(e for e in TOOL_MANIFEST if e["name"] == "searchFlights")
    assert "dynamically generated" in entry["description"]


def test_search_flights_missing_arguments():
    result = search_flights_tool(_IDENTITY, {"origin": "Aurora City"})
    assert result["error"] is True
    assert "destination" in result["message"] and "date" in result["message"]


# ── bookTicket ───────────────────────────────────────────────────────────────


def test_book_ticket_happy_path():
    result = book_ticket_tool(_IDENTITY, {
        "flight_id": "FL-101", "passengers": [_pax("Jane Doe")],
    })
    assert "error" not in result
    booking = result["booking"]
    assert booking["status"] == "booked"
    assert booking["booked_by"] == "agent-abc"
    assert booking["pnr"].startswith("PKT")


def test_book_ticket_multi_passenger_with_bags():
    result = book_ticket_tool(_IDENTITY, {
        "flight_id": "FL-101",
        "passengers": [_pax("Jane", bags=2), _pax("Timmy", "child"), _pax("Baby", "infant")],
    })
    assert "error" not in result
    pax = result["booking"]["passengers"]
    assert [p["type"] for p in pax] == ["adult", "child", "infant"]
    assert [p["bags"] for p in pax] == [2, 0, 0]
    assert len({p["seat"] for p in pax}) == 3  # one distinct seat per passenger


def test_book_ticket_child_without_adult_rejected():
    result = book_ticket_tool(_IDENTITY, {
        "flight_id": "FL-101", "passengers": [_pax("Timmy", "child")],
    })
    assert result["error"] is True
    assert "without at least one adult" in result["message"]


def test_book_ticket_infant_without_adult_rejected():
    result = book_ticket_tool(_IDENTITY, {
        "flight_id": "FL-101", "passengers": [_pax("Baby", "infant")],
    })
    assert result["error"] is True
    assert "without at least one adult" in result["message"]


def test_book_ticket_unknown_flight():
    result = book_ticket_tool(_IDENTITY, {
        "flight_id": "NOPE", "passengers": [_pax("Jane Doe")],
    })
    assert result == {"error": True, "message": "Unknown flight: NOPE"}


def test_book_ticket_missing_arguments():
    result = book_ticket_tool(_IDENTITY, {"flight_id": "FL-101"})
    assert result["error"] is True
    assert "passengers" in result["message"]


# ── generatePaymentLink ──────────────────────────────────────────────────────


def _booked_pnr(passengers: list[dict] | None = None) -> str:
    result = book_ticket_tool(_IDENTITY, {
        "flight_id": "FL-101", "passengers": passengers or [_pax("Jane Doe")],
    })
    return result["booking"]["pnr"]


def test_payment_link_happy_path():
    pnr = _booked_pnr()
    result = generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    assert "error" not in result
    assert result["payment"]["payment_url"].startswith("https://")
    # Simulated payment success → paid
    status = check_ticket_status_tool(_IDENTITY, {"pnr": pnr})
    assert status["booking"]["status"] == "paid"


def test_payment_link_always_succeeds_for_multi_passenger_booking():
    pnr = _booked_pnr([_pax("Jane"), _pax("Bob"), _pax("Kid", "child")])
    result = generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    assert "error" not in result
    assert result["payment"]["amount"] == 180 * 3
    status = check_ticket_status_tool(_IDENTITY, {"pnr": pnr})
    assert status["booking"]["status"] == "paid"


def test_payment_link_unknown_pnr():
    result = generate_payment_link_tool(_IDENTITY, {"pnr": "ZZZ999"})
    assert result["error"] is True
    assert "Unknown booking PNR" in result["message"]


def test_payment_link_missing_argument():
    result = generate_payment_link_tool(_IDENTITY, {})
    assert result == {"error": True, "message": "Missing required argument(s): pnr"}


# ── checkTicketStatus ────────────────────────────────────────────────────────


def test_ticket_status_happy_path():
    pnr = _booked_pnr()
    result = check_ticket_status_tool(_IDENTITY, {"pnr": pnr})
    assert "error" not in result
    assert result["booking"]["status"] == "booked"
    assert result["booking"]["flight"]["flight_id"] == "FL-101"
    assert result["booking"]["pnr"] == pnr


def test_ticket_status_reflects_lifecycle():
    pnr = _booked_pnr()
    generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    assert check_ticket_status_tool(_IDENTITY, {"pnr": pnr})["booking"]["status"] == "paid"
    check_in_passenger_tool(_IDENTITY, {"pnr": pnr})
    assert check_ticket_status_tool(_IDENTITY, {"pnr": pnr})["booking"]["status"] == "checked-in"


def test_ticket_status_unknown_pnr():
    result = check_ticket_status_tool(_IDENTITY, {"pnr": "ZZZ999"})
    assert result == {"error": True, "message": "Unknown booking PNR: ZZZ999"}


# ── checkInPassenger ─────────────────────────────────────────────────────────


def test_check_in_happy_path():
    pnr = _booked_pnr()
    generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    result = check_in_passenger_tool(_IDENTITY, {"pnr": pnr})
    assert "error" not in result
    assert result["booking"]["status"] == "checked-in"


def test_check_in_all_passengers_of_multi_passenger_booking():
    pnr = _booked_pnr([_pax("Jane"), _pax("Bob")])
    generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    result = check_in_passenger_tool(_IDENTITY, {"pnr": pnr})
    assert result["booking"]["status"] == "checked-in"
    assert all(p["seat"] is not None for p in result["booking"]["passengers"])


def test_check_in_before_payment_rejected():
    pnr = _booked_pnr()
    result = check_in_passenger_tool(_IDENTITY, {"pnr": pnr})
    assert result["error"] is True
    assert "paid ticket" in result["message"]


def test_check_in_unknown_pnr():
    result = check_in_passenger_tool(_IDENTITY, {"pnr": "ZZZ999"})
    assert result["error"] is True


# ── selectSeat ───────────────────────────────────────────────────────────────


def _checked_in_pnr(passengers: list[dict] | None = None) -> str:
    pnr = _booked_pnr(passengers)
    generate_payment_link_tool(_IDENTITY, {"pnr": pnr})
    check_in_passenger_tool(_IDENTITY, {"pnr": pnr})
    return pnr


def test_select_seat_happy_path():
    pnr = _checked_in_pnr()
    result = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Jane Doe", "seat": "4F"})
    assert "error" not in result
    assert result["booking"]["passengers"][0]["seat"] == "4F"


def test_select_seat_per_passenger_multi_passenger_booking():
    pnr = _checked_in_pnr([_pax("Jane"), _pax("Bob")])
    r1 = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Jane", "seat": "4F"})
    r2 = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Bob", "seat": "4E"})
    assert "error" not in r1 and "error" not in r2
    seats = {p["name"]: p["seat"] for p in r2["booking"]["passengers"]}
    assert seats == {"Jane": "4F", "Bob": "4E"}


def test_select_seat_before_check_in_rejected():
    pnr = _booked_pnr()
    result = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Jane Doe", "seat": "4F"})
    assert result["error"] is True
    assert "after check-in" in result["message"]


def test_select_occupied_seat_rejected():
    pnr = _checked_in_pnr()
    result = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Jane Doe", "seat": "1A"})  # seed hold
    assert result["error"] is True
    assert "occupied" in result["message"]


def test_select_nonexistent_seat_rejected():
    pnr = _checked_in_pnr()
    result = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Jane Doe", "seat": "99Z"})
    assert result["error"] is True
    assert "does not exist" in result["message"]


def test_select_seat_unknown_passenger_rejected():
    pnr = _checked_in_pnr()
    result = select_seat_tool(_IDENTITY, {"pnr": pnr, "passenger": "Mallory", "seat": "4F"})
    assert result["error"] is True
    assert "not on booking" in result["message"]


def test_select_seat_missing_arguments():
    result = select_seat_tool(_IDENTITY, {"pnr": "PKT001"})
    assert result["error"] is True
    assert "passenger" in result["message"] and "seat" in result["message"]


# ── cancelBooking ────────────────────────────────────────────────────────────


def test_cancel_happy_path():
    pnr = _booked_pnr()
    result = cancel_booking_tool(_IDENTITY, {"pnr": pnr})
    assert "error" not in result
    assert result["booking"]["status"] == "cancelled"
    assert all(p["seat"] is None for p in result["booking"]["passengers"])


def test_cancel_frees_all_seats_for_new_booking():
    pnr = _booked_pnr([_pax("Jane"), _pax("Bob")])
    seats = [
        p["seat"] for p in check_ticket_status_tool(_IDENTITY, {"pnr": pnr})["booking"]["passengers"]
    ]
    cancel_booking_tool(_IDENTITY, {"pnr": pnr})
    # All freed seats are available again for new bookings on the same flight
    for seat in seats:
        new = book_ticket_tool(_IDENTITY, {"flight_id": "FL-101", "passengers": [_pax("Rebook Pax")]})
        new_pnr = new["booking"]["pnr"]
        generate_payment_link_tool(_IDENTITY, {"pnr": new_pnr})
        check_in_passenger_tool(_IDENTITY, {"pnr": new_pnr})
        selected = select_seat_tool(_IDENTITY, {"pnr": new_pnr, "passenger": "Rebook Pax", "seat": seat})
        assert "error" not in selected


def test_cancel_twice_rejected():
    pnr = _booked_pnr()
    cancel_booking_tool(_IDENTITY, {"pnr": pnr})
    result = cancel_booking_tool(_IDENTITY, {"pnr": pnr})
    assert result["error"] is True
    assert "already cancelled" in result["message"]


def test_cancel_unknown_pnr():
    result = cancel_booking_tool(_IDENTITY, {"pnr": "ZZZ999"})
    assert result["error"] is True


# ── Registry / manifest wiring ───────────────────────────────────────────────


def test_registry_contains_all_booking_tools():
    assert BOOKING_TOOL_NAMES <= set(tool_registry)


def test_booking_tools_error_shape_consistent():
    """All booking tools return the structured {error, message} shape on bad input."""
    results = [
        search_flights_tool(_IDENTITY, {}),
        book_ticket_tool(_IDENTITY, {}),
        generate_payment_link_tool(_IDENTITY, {}),
        check_ticket_status_tool(_IDENTITY, {}),
        check_in_passenger_tool(_IDENTITY, {}),
        select_seat_tool(_IDENTITY, {}),
        cancel_booking_tool(_IDENTITY, {}),
    ]
    for result in results:
        assert result["error"] is True
        assert isinstance(result["message"], str)


def test_manifest_covers_all_booking_tools():
    names = {entry["name"] for entry in TOOL_MANIFEST}
    assert BOOKING_TOOL_NAMES <= names


def test_manifest_booking_schemas_have_required_fields():
    expected = {
        "searchFlights": {"origin", "destination", "date"},
        "bookTicket": {"flight_id", "passengers"},
        "generatePaymentLink": {"pnr"},
        "checkTicketStatus": {"pnr"},
        "checkInPassenger": {"pnr"},
        "selectSeat": {"pnr", "passenger", "seat"},
        "cancelBooking": {"pnr"},
    }
    for name, required in expected.items():
        entry = next(e for e in TOOL_MANIFEST if e["name"] == name)
        assert set(entry["inputSchema"]["required"]) == required
