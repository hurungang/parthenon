"""Unit tests for the in-memory booking store (app/booking_store.py).

Covers: seed determinism, reset-on-restart behaviour, seat availability
transitions, the booked → paid → checked-in → cancelled lifecycle, PNR-keyed
lookups, multi-passenger bookings, the child/infant-without-adult rule, bags,
and per-passenger seat selection.
"""
from __future__ import annotations

import pytest

from app.booking_store import (
    GENERATED_FARE_MAX,
    GENERATED_FARE_MIN,
    GENERATED_MAX_RESULTS,
    GENERATED_MIN_RESULTS,
    GENERATED_SEATS_TOTAL,
    SEAT_HOLD_SEED,
    SEED_TRAVEL_DATE,
    STATUS_BOOKED,
    STATUS_CANCELLED,
    STATUS_CHECKED_IN,
    STATUS_PAID,
    BookingError,
    BookingStore,
)


@pytest.fixture
def store() -> BookingStore:
    return BookingStore()


def _pax(name: str, pax_type: str = "adult", bags: int = 0) -> dict:
    return {"name": name, "type": pax_type, "bags": bags}


def _make_store_with_booking() -> BookingStore:
    store = BookingStore()
    store.create_booking("FL-101", [_pax("Test Passenger")], booked_by="agent-1")
    return store


def _checked_in_ref(store: BookingStore) -> tuple[str, str]:
    booking = store.create_booking("FL-101", [_pax("Seat Pax")])
    store.generate_payment_link(booking["pnr"])
    store.check_in(booking["pnr"])
    return booking["pnr"], "1A"


# ── Seed determinism & reset ─────────────────────────────────────────────────


def test_seed_is_deterministic_across_instances():
    s1, s2 = BookingStore(), BookingStore()
    assert s1.snapshot() == s2.snapshot()


def test_seed_has_flights(store):
    assert len(store.flights) == 4
    assert "FL-101" in store.flights


def test_seed_has_no_bookings(store):
    assert store.bookings == {}


def test_seed_seat_map_has_seed_holds(store):
    for seats in store.seat_map.values():
        assert seats["1A"] == SEAT_HOLD_SEED
        assert seats["2C"] == SEAT_HOLD_SEED


def test_seed_holds_are_not_rebookable(store):
    pnr, _ = _checked_in_ref(store)
    with pytest.raises(BookingError, match="occupied"):
        store.select_seat(pnr, "Seat Pax", "1A")


def test_reset_clears_bookings_and_payment_links():
    store = _make_store_with_booking()
    pnr = next(iter(store.bookings))
    store.generate_payment_link(pnr)
    store.reset()
    assert store.bookings == {}
    assert store.payment_links == {}


def test_reset_restores_identical_seed_state():
    pristine = BookingStore().snapshot()
    store = _make_store_with_booking()
    pnr = next(iter(store.bookings))
    store.generate_payment_link(pnr)
    store.cancel(pnr)
    store.reset()
    assert store.snapshot() == pristine


def test_pnrs_deterministic_after_reset():
    s1 = BookingStore()
    s2 = BookingStore()
    b1 = s1.create_booking("FL-101", [_pax("Pax A")])
    b2 = s2.create_booking("FL-101", [_pax("Pax A")])
    assert b1["pnr"] == b2["pnr"]


def test_pnr_format_six_char_alphanumeric(store):
    booking = store.create_booking("FL-101", [_pax("Pax A")])
    pnr = booking["pnr"]
    assert len(pnr) == 6
    assert pnr.isalnum()
    assert pnr.startswith("PKT")


# ── Flight search ────────────────────────────────────────────────────────────


def test_search_flights_matches_route_and_date(store):
    results = store.search_flights("Aurora City", "Meridian Falls", SEED_TRAVEL_DATE)
    assert {f["flight_id"] for f in results} == {"FL-101", "FL-102", "FL-103"}


def test_search_flights_case_insensitive_city(store):
    results = store.search_flights("aurora city", "MERIDIAN FALLS", SEED_TRAVEL_DATE)
    assert len(results) == 3


def test_search_flights_arbitrary_route_generates_flights(store):
    results = store.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    assert GENERATED_MIN_RESULTS <= len(results) <= GENERATED_MAX_RESULTS
    for flight in results:
        assert flight["origin"] == "Nowhere"
        assert flight["destination"] == "Elsewhere"
        assert flight["departure_date"] == SEED_TRAVEL_DATE


def test_generated_flights_are_deterministic_per_query():
    s1, s2 = BookingStore(), BookingStore()
    r1 = s1.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    r2 = s2.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    assert [f["flight_id"] for f in r1] == [f["flight_id"] for f in r2]
    assert r1 == r2


def test_repeated_search_does_not_duplicate_generated_flights(store):
    first = store.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    second = store.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    assert [f["flight_id"] for f in first] == [f["flight_id"] for f in second]
    assert len(second) == len(first)


def test_generated_flights_have_valid_shape_and_fresh_seat_map(store):
    results = store.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    for flight in results:
        assert GENERATED_FARE_MIN <= flight["fare"] <= GENERATED_FARE_MAX
        assert flight["seats_total"] == GENERATED_SEATS_TOTAL
        assert flight["seats_available"] == GENERATED_SEATS_TOTAL  # no holds
        assert flight["flight_id"] in store.flights
        assert flight["flight_id"] in store.seat_map
        assert flight["departure_time"] != flight["arrival_time"]


def test_generated_flight_ids_follow_prefix(store):
    results = store.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    assert all(f["flight_id"].startswith("FL-") for f in results)


def test_search_flights_same_origin_destination_rejected(store):
    with pytest.raises(BookingError, match="must be different"):
        store.search_flights("Aurora City", "aurora city", SEED_TRAVEL_DATE)


def test_generated_flight_full_lifecycle(store):
    """Generated flights are fully operable by every downstream operation."""
    results = store.search_flights("Nowhere", "Elsewhere", SEED_TRAVEL_DATE)
    flight_id = results[0]["flight_id"]
    fare = results[0]["fare"]
    booking = store.create_booking(
        flight_id, [_pax("Jane Doe"), _pax("Timmy Doe", "child", bags=1)], booked_by="agent-1"
    )
    pnr = booking["pnr"]
    assert booking["status"] == STATUS_BOOKED
    assert len({p["seat"] for p in booking["passengers"]}) == 2
    link = store.generate_payment_link(pnr)
    assert store.bookings[pnr].status == STATUS_PAID
    assert link["amount"] == fare * 2
    assert store.get_booking(pnr)["flight"]["flight_id"] == flight_id
    store.check_in(pnr)
    assert store.bookings[pnr].status == STATUS_CHECKED_IN
    updated = store.select_seat(pnr, "Jane Doe", "4F")
    assert updated["passengers"][0]["seat"] == "4F"
    store.cancel(pnr)
    assert store.bookings[pnr].status == STATUS_CANCELLED
    assert store.seat_map[flight_id]["4F"] is None
    # Re-book works after cancellation
    rebooking = store.create_booking(flight_id, [_pax("Bob Ray")])
    assert rebooking["status"] == STATUS_BOOKED


def test_search_results_include_seats_available(store):
    results = store.search_flights("Aurora City", "Meridian Falls", SEED_TRAVEL_DATE)
    for flight in results:
        assert flight["seats_available"] == 22  # 24 total − 2 seed holds


# ── Booking creation (PNR, passengers, validation) ──────────────────────────


def test_create_booking_starts_booked(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")], booked_by="agent-1")
    assert booking["status"] == STATUS_BOOKED
    assert booking["flight_id"] == "FL-101"
    assert booking["booked_by"] == "agent-1"
    assert store.bookings[booking["pnr"]].status == STATUS_BOOKED


def test_create_booking_single_passenger_defaults(store):
    booking = store.create_booking("FL-101", [{"name": "Jane Doe"}])
    assert booking["passengers"][0]["type"] == "adult"
    assert booking["passengers"][0]["bags"] == 0


def test_create_booking_multi_passenger(store):
    booking = store.create_booking("FL-101", [
        _pax("Jane Doe"),
        _pax("Timmy Doe", "child", bags=1),
        _pax("Baby Doe", "infant"),
    ])
    assert [p["name"] for p in booking["passengers"]] == ["Jane Doe", "Timmy Doe", "Baby Doe"]
    assert [p["type"] for p in booking["passengers"]] == ["adult", "child", "infant"]
    assert [p["bags"] for p in booking["passengers"]] == [0, 1, 0]


def test_create_booking_reserves_one_seat_per_passenger(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe"), _pax("Bob Ray")])
    seats = [p["seat"] for p in booking["passengers"]]
    assert all(s is not None for s in seats)
    assert len(set(seats)) == 2  # distinct seats
    for seat in seats:
        assert store.seat_map["FL-101"][seat] == booking["pnr"]


def test_create_booking_unknown_flight_raises(store):
    with pytest.raises(BookingError, match="Unknown flight"):
        store.create_booking("NOPE-1", [_pax("Jane Doe")])


def test_create_booking_empty_passenger_list_raises(store):
    with pytest.raises(BookingError, match="At least one passenger"):
        store.create_booking("FL-101", [])


def test_create_booking_empty_passenger_name_raises(store):
    with pytest.raises(BookingError, match="Passenger name"):
        store.create_booking("FL-101", [{"name": "   "}])


def test_create_booking_invalid_passenger_type_raises(store):
    with pytest.raises(BookingError, match="Invalid passenger type"):
        store.create_booking("FL-101", [{"name": "Jane", "type": "senior"}])


def test_create_booking_duplicate_passenger_name_raises(store):
    with pytest.raises(BookingError, match="Duplicate passenger name"):
        store.create_booking("FL-101", [_pax("Jane"), _pax("Jane")])


def test_create_booking_negative_bags_raises(store):
    with pytest.raises(BookingError, match="Bag count"):
        store.create_booking("FL-101", [{"name": "Jane", "bags": -1}])


def test_create_booking_child_without_adult_rejected(store):
    with pytest.raises(BookingError, match="without at least one adult"):
        store.create_booking("FL-101", [_pax("Timmy Doe", "child")])


def test_create_booking_infant_without_adult_rejected(store):
    with pytest.raises(BookingError, match="without at least one adult"):
        store.create_booking("FL-101", [_pax("Baby Doe", "infant")])


def test_create_booking_two_children_without_adult_rejected(store):
    with pytest.raises(BookingError, match="without at least one adult"):
        store.create_booking("FL-101", [_pax("Kid A", "child"), _pax("Kid B", "child")])


def test_create_booking_child_with_adult_accepted(store):
    booking = store.create_booking("FL-101", [_pax("Jane"), _pax("Kid", "child")])
    assert booking["status"] == STATUS_BOOKED
    assert len(booking["passengers"]) == 2


def test_create_booking_not_enough_seats_raises(store):
    # No validation error, but the seat-availability guard applies per booking.
    small = BookingStore()
    booking = small.create_booking("FL-101", [_pax(f"Pax {i}") for i in range(22)])
    assert len(booking["passengers"]) == 22
    with pytest.raises(BookingError, match="enough free seats"):
        small.create_booking("FL-101", [_pax("One More")])


# ── Booking lifecycle ────────────────────────────────────────────────────────


def test_full_lifecycle_booked_paid_checked_in(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    assert store.bookings[pnr].status == STATUS_PAID
    store.check_in(pnr)
    assert store.bookings[pnr].status == STATUS_CHECKED_IN


def test_get_booking_includes_flight_and_passengers(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe"), _pax("Kid", "child", bags=1)])
    result = store.get_booking(booking["pnr"])
    assert result["flight"]["flight_id"] == "FL-101"
    assert result["flight"]["fare"] == 180
    assert {p["name"] for p in result["passengers"]} == {"Jane Doe", "Kid"}


def test_get_booking_by_pnr(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    assert store.get_booking(booking["pnr"])["pnr"] == booking["pnr"]


def test_get_booking_unknown_pnr_raises(store):
    with pytest.raises(BookingError, match="Unknown booking PNR"):
        store.get_booking("ZZZ999")


# ── Payment link ─────────────────────────────────────────────────────────────


def test_payment_link_only_for_booked(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    link = store.generate_payment_link(booking["pnr"])
    assert link["payment_url"].startswith("https://")
    assert store.bookings[booking["pnr"]].status == STATUS_PAID


def test_payment_link_unknown_booking_raises(store):
    with pytest.raises(BookingError):
        store.generate_payment_link("ZZZ999")


def test_payment_link_idempotent_when_paid(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    link1 = store.generate_payment_link(pnr)
    link2 = store.generate_payment_link(pnr)
    assert link1 == link2


def test_payment_link_rejected_after_cancel(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    store.cancel(booking["pnr"])
    with pytest.raises(BookingError, match="booked tickets"):
        store.generate_payment_link(booking["pnr"])


def test_payment_always_succeeds_regardless_of_passenger_count(store):
    """Generating the link immediately marks the booking paid, no matter how
    many passengers are on it (amount = fare × passenger count)."""
    booking = store.create_booking("FL-101", [
        _pax("Jane"), _pax("Bob"), _pax("Kid", "child"), _pax("Baby", "infant"),
    ])
    link = store.generate_payment_link(booking["pnr"])
    assert store.bookings[booking["pnr"]].status == STATUS_PAID
    assert link["amount"] == 180 * 4


# ── Check-in ─────────────────────────────────────────────────────────────────


def test_check_in_requires_paid(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    with pytest.raises(BookingError, match="paid ticket"):
        store.check_in(booking["pnr"])


def test_check_in_twice_raises(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    with pytest.raises(BookingError, match="already checked in"):
        store.check_in(pnr)


def test_check_in_cancelled_raises(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    store.cancel(booking["pnr"])
    with pytest.raises(BookingError):
        store.check_in(booking["pnr"])


def test_check_in_checks_in_all_passengers(store):
    booking = store.create_booking("FL-101", [_pax("Jane"), _pax("Bob"), _pax("Kid", "child")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    updated = store.check_in(pnr)
    assert updated["status"] == STATUS_CHECKED_IN
    # Booking-level state: every passenger on the booking is checked in with it
    assert all(p["seat"] is not None for p in updated["passengers"])


# ── Seat selection (per passenger) ───────────────────────────────────────────


def test_select_seat_requires_checked_in(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    with pytest.raises(BookingError, match="after check-in"):
        store.select_seat(booking["pnr"], "Jane Doe", "3A")


def test_select_seat_happy_path(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    updated = store.select_seat(pnr, "Jane Doe", "4F")
    assert updated["passengers"][0]["seat"] == "4F"
    assert store.seat_map["FL-101"]["4F"] == pnr


def test_select_seat_unknown_passenger_raises(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    with pytest.raises(BookingError, match="not on booking"):
        store.select_seat(pnr, "Mallory", "4F")


def test_select_seat_per_passenger_in_multi_passenger_booking(store):
    booking = store.create_booking("FL-101", [_pax("Jane"), _pax("Bob")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    updated = store.select_seat(pnr, "Jane", "4F")
    updated = store.select_seat(pnr, "Bob", "4E")
    seats = {p["name"]: p["seat"] for p in updated["passengers"]}
    assert seats == {"Jane": "4F", "Bob": "4E"}
    assert store.seat_map["FL-101"]["4F"] == pnr
    assert store.seat_map["FL-101"]["4E"] == pnr


def test_select_nonexistent_seat_raises(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    with pytest.raises(BookingError, match="does not exist"):
        store.select_seat(pnr, "Jane Doe", "99Z")


def test_select_occupied_seat_raises(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    with pytest.raises(BookingError, match="occupied"):
        store.select_seat(pnr, "Jane Doe", "1A")


def test_reselect_seat_frees_passenger_previous(store):
    booking = store.create_booking("FL-101", [_pax("Jane"), _pax("Bob")])
    pnr = booking["pnr"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    store.select_seat(pnr, "Jane", "3B")
    updated = store.select_seat(pnr, "Jane", "3D")
    seats = {p["name"]: p["seat"] for p in updated["passengers"]}
    assert seats["Jane"] == "3D"
    assert seats["Bob"] is not None  # other passenger unaffected
    assert store.seat_map["FL-101"]["3B"] is None


# ── Cancellation & re-book ───────────────────────────────────────────────────


def test_cancel_frees_seat(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    seat = booking["passengers"][0]["seat"]
    store.cancel(pnr)
    assert store.bookings[pnr].status == STATUS_CANCELLED
    assert store.bookings[pnr].passengers[0].seat is None
    assert store.seat_map["FL-101"][seat] is None


def test_cancel_frees_all_passenger_seats(store):
    booking = store.create_booking("FL-101", [_pax("Jane"), _pax("Bob"), _pax("Kid", "child")])
    pnr = booking["pnr"]
    seats = [p["seat"] for p in booking["passengers"]]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    store.select_seat(pnr, "Jane", "4A")
    store.cancel(pnr)
    assert store.bookings[pnr].status == STATUS_CANCELLED
    assert all(p.seat is None for p in store.bookings[pnr].passengers)
    for seat in [*seats, "4A"]:
        assert store.seat_map["FL-101"][seat] is None


def test_cancelled_booking_rebookable_same_flight(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    pnr = booking["pnr"]
    seat = booking["passengers"][0]["seat"]
    store.generate_payment_link(pnr)
    store.check_in(pnr)
    store.select_seat(pnr, "Jane Doe", "4A")
    store.cancel(pnr)
    # New booking on the same flight gets the freed seat
    new_booking = store.create_booking("FL-101", [_pax("Bob Ray")])
    new_pnr = new_booking["pnr"]
    store.generate_payment_link(new_pnr)
    store.check_in(new_pnr)
    new = store.select_seat(new_pnr, "Bob Ray", "4A")
    assert new["passengers"][0]["seat"] == "4A"


def test_cancel_twice_raises(store):
    booking = store.create_booking("FL-101", [_pax("Jane Doe")])
    store.cancel(booking["pnr"])
    with pytest.raises(BookingError, match="already cancelled"):
        store.cancel(booking["pnr"])


def test_cancel_unknown_booking_raises(store):
    with pytest.raises(BookingError):
        store.cancel("ZZZ999")
