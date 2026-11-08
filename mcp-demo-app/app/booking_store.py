"""In-memory airline booking store for the scenario-based MCP demo.

All state is process-local and fictional. The store is rebuilt from a
deterministic seed on every app startup (see ``reset``), so restarting the
demo app always yields identical data — no persistence, no external calls,
no database involvement.

Domain model:
- A **booking** is identified by its PNR (6-character alphanumeric,
  deterministically generated, e.g. ``PKT001``). Every fetch-style tool keys
  off the PNR.
- A booking owns one or more **passengers** (name, passenger type
  ``adult`` / ``child`` / ``infant``, and a bag count, default 0). A child or
  infant cannot travel without at least one adult on the same booking.
- Seats are held per passenger; seat selection (post check-in) is per
  passenger via PNR + passenger name + seat.

Ticket lifecycle (booking level): booked → paid → checked-in → cancelled.
Seat map per flight: free ↔ occupied (occupied seats reference the holding
booking's PNR, or the literal ``SEED_HOLD`` for the deterministic seed holds).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Lifecycle states ─────────────────────────────────────────────────────────

STATUS_BOOKED = "booked"
STATUS_PAID = "paid"
STATUS_CHECKED_IN = "checked-in"
STATUS_CANCELLED = "cancelled"

SEAT_HOLD_SEED = "SEED_HOLD"

# Passenger types. A child/infant requires at least one adult on the booking.
PAX_ADULT = "adult"
PAX_CHILD = "child"
PAX_INFANT = "infant"
PAX_TYPES = (PAX_ADULT, PAX_CHILD, PAX_INFANT)

# Fixed fictional travel date used by the seed flights. Deterministic so the
# demo script is always reproducible.
SEED_TRAVEL_DATE = "2030-03-15"


class BookingError(Exception):
    """Raised by store operations on invalid references or illegal transitions."""


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class Flight:
    flight_id: str
    origin: str
    destination: str
    departure_date: str
    departure_time: str
    arrival_time: str
    fare: int
    seats_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "flight_id": self.flight_id,
            "origin": self.origin,
            "destination": self.destination,
            "departure_date": self.departure_date,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "fare": self.fare,
            "seats_total": self.seats_total,
        }


@dataclass
class Passenger:
    name: str
    pax_type: str
    bags: int = 0
    seat: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.pax_type,
            "bags": self.bags,
            "seat": self.seat,
        }


@dataclass
class Booking:
    pnr: str
    flight_id: str
    passengers: list[Passenger] = field(default_factory=list)
    status: str = STATUS_BOOKED
    booked_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pnr": self.pnr,
            "flight_id": self.flight_id,
            "passengers": [p.to_dict() for p in self.passengers],
            "status": self.status,
            "booked_by": self.booked_by,
        }


# ── Seed data (fictional, minimal, deterministic) ────────────────────────────

_SEED_FLIGHTS: list[Flight] = [
    Flight("FL-101", "Aurora City", "Meridian Falls", SEED_TRAVEL_DATE, "08:30", "09:45", 180, 24),
    Flight("FL-102", "Aurora City", "Meridian Falls", SEED_TRAVEL_DATE, "12:15", "13:30", 220, 24),
    Flight("FL-103", "Aurora City", "Meridian Falls", SEED_TRAVEL_DATE, "18:00", "19:15", 260, 24),
    Flight("FL-201", "Meridian Falls", "Aurora City", SEED_TRAVEL_DATE, "20:30", "21:45", 190, 24),
]

_SEAT_ROWS = (1, 2, 3, 4)
_SEAT_COLS = ("A", "B", "C", "D", "E", "F")

# Deterministic per-flight seed holds: the same two seats are occupied on
# every flight, on every restart, so seat-availability demos are predictable.
_SEED_HELD_SEATS = ("1A", "2C")


def _build_seed_seat_map() -> dict[str, dict[str, str | None]]:
    seat_map: dict[str, dict[str, str | None]] = {}
    for flight in _SEED_FLIGHTS:
        seats: dict[str, str | None] = {
            f"{row}{col}": None for row in _SEAT_ROWS for col in _SEAT_COLS
        }
        for seat in _SEED_HELD_SEATS:
            seats[seat] = SEAT_HOLD_SEED
        seat_map[flight.flight_id] = seats
    return seat_map


# ── Store ────────────────────────────────────────────────────────────────────


class BookingStore:
    """In-memory flights / bookings (PNR-keyed) / seat map / payment links."""

    def __init__(self) -> None:
        self.reset()

    # ── Seeding / reset ──────────────────────────────────────────────────

    def reset(self) -> None:
        """Rebuild the store from the deterministic seed (startup = reset)."""
        self.flights: dict[str, Flight] = {f.flight_id: f for f in _SEED_FLIGHTS}
        self.seat_map: dict[str, dict[str, str | None]] = _build_seed_seat_map()
        self.bookings: dict[str, Booking] = {}
        self.payment_links: dict[str, dict[str, Any]] = {}
        self._booking_counter = 0

    # ── Helpers ──────────────────────────────────────────────────────────

    def _require_flight(self, flight_id: str) -> Flight:
        flight = self.flights.get(flight_id)
        if flight is None:
            raise BookingError(f"Unknown flight: {flight_id}")
        return flight

    def _require_booking(self, pnr: str) -> Booking:
        booking = self.bookings.get(pnr)
        if booking is None:
            raise BookingError(f"Unknown booking PNR: {pnr}")
        return booking

    def _seats_available(self, flight_id: str) -> int:
        return sum(1 for holder in self.seat_map[flight_id].values() if holder is None)

    def _reserve_seat(self, flight_id: str, pnr: str, passenger: Passenger) -> None:
        seats = self.seat_map[flight_id]
        for seat, holder in seats.items():
            if holder is None:
                seats[seat] = pnr
                passenger.seat = seat
                return
        raise BookingError(f"No free seats left on flight {flight_id}")

    def snapshot(self) -> dict[str, Any]:
        """Full store state — used by tests and reset verification."""
        return {
            "flights": {fid: f.to_dict() for fid, f in self.flights.items()},
            "seat_map": {fid: dict(seats) for fid, seats in self.seat_map.items()},
            "bookings": {pnr: b.to_dict() for pnr, b in self.bookings.items()},
            "payment_links": dict(self.payment_links),
        }

    # ── Read operations ──────────────────────────────────────────────────

    def search_flights(self, origin: str, destination: str, date: str) -> list[dict[str, Any]]:
        """Return seed flights matching origin/destination/date (read-only)."""
        results: list[dict[str, Any]] = []
        for flight in self.flights.values():
            if (
                flight.origin.lower() == origin.strip().lower()
                and flight.destination.lower() == destination.strip().lower()
                and flight.departure_date == date
            ):
                entry = flight.to_dict()
                entry["seats_available"] = self._seats_available(flight.flight_id)
                results.append(entry)
        return results

    def get_flight(self, flight_id: str) -> dict[str, Any]:
        flight = self._require_flight(flight_id)
        entry = flight.to_dict()
        entry["seats_available"] = self._seats_available(flight.flight_id)
        return entry

    def get_booking(self, pnr: str) -> dict[str, Any]:
        booking = self._require_booking(pnr)
        result = booking.to_dict()
        flight = self.flights.get(booking.flight_id)
        if flight is not None:
            result["flight"] = flight.to_dict()
        return result

    # ── Write operations (invoked only via MCP tools) ────────────────────

    def create_booking(
        self,
        flight_id: str,
        passengers: list[dict[str, Any]],
        booked_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a booking (PNR-keyed) for one or more passengers.

        Each passenger entry: ``{"name": str, "type": adult|child|infant,
        "bags": int (optional, default 0)}``. At least one passenger is
        required; a child or infant cannot travel without at least one adult
        on the same booking. One seat is reserved per passenger.
        """
        self._require_flight(flight_id)
        if not passengers or not isinstance(passengers, list):
            raise BookingError("At least one passenger is required")
        parsed: list[Passenger] = []
        seen_names: set[str] = set()
        for entry in passengers:
            if not isinstance(entry, dict):
                raise BookingError("Each passenger must be an object with name and type")
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                raise BookingError("Passenger name must not be empty")
            name = name.strip()
            if name.lower() in seen_names:
                raise BookingError(f"Duplicate passenger name on booking: {name}")
            seen_names.add(name.lower())
            pax_type = entry.get("type", PAX_ADULT)
            if pax_type not in PAX_TYPES:
                raise BookingError(
                    f"Invalid passenger type: {pax_type!r} (expected one of {', '.join(PAX_TYPES)})"
                )
            bags = entry.get("bags", 0)
            if not isinstance(bags, int) or isinstance(bags, bool) or bags < 0:
                raise BookingError(f"Bag count must be a non-negative integer (passenger {name})")
            parsed.append(Passenger(name=name, pax_type=pax_type, bags=bags))
        adults = [p for p in parsed if p.pax_type == PAX_ADULT]
        dependents = [p for p in parsed if p.pax_type in (PAX_CHILD, PAX_INFANT)]
        if dependents and not adults:
            raise BookingError(
                "A child or infant cannot travel without at least one adult on the same booking"
            )
        if self._seats_available(flight_id) < len(parsed):
            raise BookingError(f"Flight {flight_id} does not have enough free seats")

        self._booking_counter += 1
        pnr = f"PKT{self._booking_counter:03d}"
        booking = Booking(
            pnr=pnr,
            flight_id=flight_id,
            passengers=parsed,
            status=STATUS_BOOKED,
            booked_by=booked_by,
        )
        self.bookings[pnr] = booking
        for passenger in parsed:
            self._reserve_seat(flight_id, pnr, passenger)
        return booking.to_dict()

    def generate_payment_link(self, pnr: str) -> dict[str, Any]:
        """Create a fictional payment link; completing the demo 'payment'.

        The demo simulates immediate payment success: the booking transitions
        booked → paid so the check-in step of the journey is reachable with
        exactly seven tools (no separate 'pay' tool). The amount is the
        flight fare × passenger count.
        """
        booking = self._require_booking(pnr)
        if booking.status == STATUS_PAID:
            link = self.payment_links.get(pnr)
            if link is not None:
                return dict(link)
        if booking.status != STATUS_BOOKED:
            raise BookingError(
                f"Payment link can only be generated for booked tickets "
                f"(current status: {booking.status})"
            )
        fare = self.flights[booking.flight_id].fare
        link = {
            "pnr": pnr,
            "payment_url": f"https://payments.demo-parthenon.example/pay/{pnr}",
            "amount": fare * len(booking.passengers),
            "currency": "CRED",
            "status": "paid (simulated — no real payment)",
        }
        self.payment_links[pnr] = link
        booking.status = STATUS_PAID
        return dict(link)

    def check_in(self, pnr: str) -> dict[str, Any]:
        """Check in the whole booking (paid → checked-in); every passenger on
        the booking is checked in with it."""
        booking = self._require_booking(pnr)
        if booking.status == STATUS_CHECKED_IN:
            raise BookingError("Booking is already checked in")
        if booking.status != STATUS_PAID:
            raise BookingError(
                f"Check-in requires a paid ticket (current status: {booking.status})"
            )
        booking.status = STATUS_CHECKED_IN
        return booking.to_dict()

    def select_seat(self, pnr: str, passenger_name: str, seat: str) -> dict[str, Any]:
        """Assign a seat to one passenger of a checked-in booking."""
        booking = self._require_booking(pnr)
        if booking.status != STATUS_CHECKED_IN:
            raise BookingError(
                f"Seat selection is only allowed after check-in (current status: {booking.status})"
            )
        passenger = next(
            (p for p in booking.passengers if p.name.lower() == passenger_name.strip().lower()),
            None,
        )
        if passenger is None:
            known = ", ".join(p.name for p in booking.passengers)
            raise BookingError(
                f"Passenger {passenger_name!r} is not on booking {pnr} (passengers: {known})"
            )
        seats = self.seat_map[booking.flight_id]
        if seat not in seats:
            raise BookingError(f"Seat {seat} does not exist on flight {booking.flight_id}")
        holder = seats[seat]
        if holder is not None:
            if holder == pnr and passenger.seat == seat:
                pass  # re-selecting the same seat is a no-op
            else:
                raise BookingError(f"Seat {seat} is already occupied")
        else:
            # Free this passenger's previous seat so it becomes re-bookable
            if passenger.seat is not None:
                seats[passenger.seat] = None
            seats[seat] = pnr
        passenger.seat = seat
        return booking.to_dict()

    def cancel(self, pnr: str) -> dict[str, Any]:
        """Cancel the whole booking; frees the seats of all its passengers."""
        booking = self._require_booking(pnr)
        if booking.status == STATUS_CANCELLED:
            raise BookingError("Booking is already cancelled")
        seats = self.seat_map.get(booking.flight_id, {})
        for passenger in booking.passengers:
            if passenger.seat is not None and seats.get(passenger.seat) == pnr:
                seats[passenger.seat] = None
            passenger.seat = None
        booking.status = STATUS_CANCELLED
        return booking.to_dict()


# ── Module-level singleton (seeded at app startup via reset) ─────────────────

booking_store = BookingStore()


def reset_booking_store() -> None:
    """Reset/reseed the singleton store. Called from the app lifespan."""
    booking_store.reset()
