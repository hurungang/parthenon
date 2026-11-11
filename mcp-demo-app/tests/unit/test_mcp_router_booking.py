"""Unit tests: booking tools through the MCP JSON-RPC endpoint.

Extends the router tests: tools/list includes booking tools; tools/call
dispatches booking tool names with arguments and returns structured results.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routes.health import health_router
from app.routes.mcp import mcp_router
from app.booking_store import SEED_TRAVEL_DATE, BookingStore


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(mcp_router)
    return app


@pytest.fixture
async def client(test_app):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    from app import booking_store as bs_module
    from app import tools as tools_module

    store = BookingStore()
    monkeypatch.setattr(bs_module, "booking_store", store)
    monkeypatch.setattr(tools_module, "booking_store", store)
    return store


_AUTH = {"Authorization": "Bearer fake.jwt.token"}
_IDENTITY = {"sub": "agent-abc", "iss": "http://kc/realms/ai_agents", "mcp_role": "demo_agent"}


def _call(name: str, arguments: dict | None = None, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }


async def _tools_call(client, name: str, arguments: dict | None = None) -> dict:
    with patch(
        "app.routes.mcp.get_agent_identity",
        new=AsyncMock(return_value=_IDENTITY),
    ):
        response = await client.post("/mcp", json=_call(name, arguments), headers=_AUTH)
    assert response.status_code == 200
    return response.json()


# ── tools/list ───────────────────────────────────────────────────────────────


async def test_tools_list_includes_booking_tools(client):
    body = (
        await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    ).json()
    names = {t["name"] for t in body["result"]["tools"]}
    assert {
        "searchFlights", "bookTicket", "generatePaymentLink",
        "checkTicketStatus", "checkInPassenger", "selectSeat", "cancelBooking",
    } <= names


async def test_tools_list_greeting_tools_still_present(client):
    body = (
        await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    ).json()
    names = {t["name"] for t in body["result"]["tools"]}
    assert {"helloWorld", "helloAgent", "helloUser"} <= names


# ── tools/call — searchFlights ───────────────────────────────────────────────


async def test_call_search_flights_returns_results(client):
    body = await _tools_call(client, "searchFlights", {
        "origin": "Aurora City", "destination": "Meridian Falls", "date": SEED_TRAVEL_DATE,
    })
    result = body["result"]["result"]
    assert "error" not in result
    assert result["count"] == 3


async def test_call_search_flights_missing_args_is_structured_error(client):
    body = await _tools_call(client, "searchFlights", {})
    assert body["result"]["result"]["error"] is True


async def test_call_search_flights_arbitrary_route_generates_results(client):
    body = await _tools_call(client, "searchFlights", {
        "origin": "Port Lumina", "destination": "Vega Hollow", "date": "2031-07-04",
    })
    result = body["result"]["result"]
    assert "error" not in result
    assert 3 <= result["count"] <= 5


# ── tools/call — bookTicket ──────────────────────────────────────────────────


async def test_call_book_ticket_creates_booking(client):
    body = await _tools_call(client, "bookTicket", {
        "flight_id": "FL-101",
        "passengers": [{"name": "Jane Doe", "type": "adult", "bags": 1}],
    })
    result = body["result"]["result"]
    booking = result["booking"]
    assert booking["status"] == "booked"
    assert booking["booked_by"] == "agent-abc"
    assert len(booking["pnr"]) == 6 and booking["pnr"].isalnum()
    assert booking["passengers"][0]["bags"] == 1
    assert f"PNR {booking['pnr']}" in result["message"]


async def test_call_book_ticket_multi_passenger(client):
    body = await _tools_call(client, "bookTicket", {
        "flight_id": "FL-101",
        "passengers": [
            {"name": "Jane Doe"},
            {"name": "Timmy Doe", "type": "child", "bags": 1},
        ],
    })
    booking = body["result"]["result"]["booking"]
    assert [p["type"] for p in booking["passengers"]] == ["adult", "child"]
    assert len({p["seat"] for p in booking["passengers"]}) == 2


async def test_call_book_ticket_child_without_adult_is_structured_error(client):
    body = await _tools_call(client, "bookTicket", {
        "flight_id": "FL-101",
        "passengers": [{"name": "Timmy Doe", "type": "child"}],
    })
    result = body["result"]["result"]
    assert result["error"] is True
    assert "without at least one adult" in result["message"]


async def test_call_book_ticket_unknown_flight_is_error(client):
    body = await _tools_call(client, "bookTicket", {
        "flight_id": "NOPE",
        "passengers": [{"name": "Jane Doe"}],
    })
    assert body["result"]["result"]["error"] is True


# ── tools/call — full journey ────────────────────────────────────────────────


async def test_call_full_journey_book_pay_checkin_seat(client):
    book = await _tools_call(client, "bookTicket", {
        "flight_id": "FL-102",
        "passengers": [{"name": "Jane Doe"}, {"name": "Bob Ray"}],
    })
    pnr = book["result"]["result"]["booking"]["pnr"]

    pay = await _tools_call(client, "generatePaymentLink", {"pnr": pnr})
    payment = pay["result"]["result"]["payment"]
    assert payment["payment_url"].startswith("https://")
    assert payment["status"].startswith("paid")
    assert payment["amount"] == 220 * 2  # fare × passenger count

    checkin = await _tools_call(client, "checkInPassenger", {"pnr": pnr})
    assert checkin["result"]["result"]["booking"]["status"] == "checked-in"
    assert "Jane Doe" in checkin["result"]["result"]["message"]

    seat = await _tools_call(
        client, "selectSeat", {"pnr": pnr, "passenger": "Jane Doe", "seat": "3C"}
    )
    booking = seat["result"]["result"]["booking"]
    seats = {p["name"]: p["seat"] for p in booking["passengers"]}
    assert seats["Jane Doe"] == "3C"
    assert seats["Bob Ray"] is not None

    status = await _tools_call(client, "checkTicketStatus", {"pnr": pnr})
    assert status["result"]["result"]["booking"]["status"] == "checked-in"


async def test_call_cancel_and_rebook(client, fresh_store):
    book = await _tools_call(client, "bookTicket", {
        "flight_id": "FL-101",
        "passengers": [{"name": "Jane Doe"}, {"name": "Bob Ray"}],
    })
    pnr = book["result"]["result"]["booking"]["pnr"]
    occupied = book["result"]["result"]["booking"]["passengers"]
    cancel = await _tools_call(client, "cancelBooking", {"pnr": pnr})
    assert cancel["result"]["result"]["booking"]["status"] == "cancelled"
    # All passenger seats freed on the seat map
    for p in occupied:
        assert fresh_store.seat_map["FL-101"][p["seat"]] is None

    rebook = await _tools_call(client, "bookTicket", {
        "flight_id": "FL-101",
        "passengers": [{"name": "Carol Ray"}],
    })
    assert rebook["result"]["result"]["booking"]["status"] == "booked"


async def test_call_unknown_pnr_is_structured_error(client):
    body = await _tools_call(client, "checkTicketStatus", {"pnr": "ZZZ999"})
    result = body["result"]["result"]
    assert result["error"] is True
    assert "Unknown booking PNR" in result["message"]


# ── tools/call — greeting tools unchanged ────────────────────────────────────


async def test_call_hello_world_still_works(client):
    body = await _tools_call(client, "helloWorld", None)
    assert body["result"]["result"]["message"] == "Hello from MCP Demo App!"
