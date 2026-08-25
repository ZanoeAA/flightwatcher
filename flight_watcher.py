#!/usr/bin/env python3
"""
Flight Price Watcher — TLV to San Francisco (SFO)
=====================================================
Goal: reach SFO from TLV, where every alternative must be either:
  (a) NONSTOP on El Al, or
  (b) ONE-STOP where the Israel-touching leg (TLV departure on the way out,
      TLV arrival on the way back) is on an Israeli airline
      (El Al, Arkia, or Israir).

This mirrors your actual booking: TLV -> LAX on El Al, then a free
United-miles hop LAX -> SFO. We're watching for a genuinely better way to
reach SFO directly under the same "Israeli airline touching Israel" rule.

Uses FlightAPI.io (https://www.flightapi.io) since Amadeus's free
self-service portal was decommissioned in July 2026.

IMPORTANT — free tier credits are limited (~20-30 total, 2 credits/check).
This script is designed to run every 10 days, NOT daily, to stay within
the free quota. Set up your scheduler (see README.md) accordingly.

Alerts you by email if it finds a valid alternative cheaper than what you
paid. Automatically stops once STOP_DATE has passed.

All secrets are read from environment variables — never hard-code them:
    FLIGHTAPI_KEY
    EMAIL_FROM          (the Gmail address the alert is sent from)
    EMAIL_APP_PASSWORD  (a Gmail "app password", not your normal password)
    EMAIL_TO            (where you want to receive alerts)
"""

import os
import sys
import csv
import smtplib
from datetime import date, datetime
from email.mime.text import MIMEText

import requests

# ─────────────────────────────────────────────────────────────────────────
# 1. TRIP CONFIGURATION — edit this block if your details ever change
# ─────────────────────────────────────────────────────────────────────────
ORIGIN = "TLV"
DESTINATION = "SFO"

OUTBOUND_DATE = "2026-12-04"
RETURN_DATE = "2026-12-21"
ADULTS = 2
CHILDREN = 0
INFANTS = 0
TRAVEL_CLASS = "Premium_Economy"  # FlightAPI expects: Economy, Business, First, Premium_Economy
CURRENCY = "USD"
REGION = "US"  # ISO country code used to check local pricing

# Israeli airlines — the leg touching Israel must be one of these.
# El Al is also the only one allowed to operate the WHOLE nonstop trip.
ISRAELI_AIRLINES = {"LY", "IZ", "6H"}  # El Al, Arkia, Israir
NONSTOP_ONLY_AIRLINE = "LY"

AMOUNT_PAID_USD = 7650.00   # total you paid for both adults, round trip (incl. the free LAX-SFO miles hop)

# Stop searching this many days before departure
DAYS_BEFORE_DEPARTURE_TO_STOP = 3
STOP_DATE = date(2026, 12, 1)   # Dec 4 minus 3 days, computed for clarity/safety

LOG_FILE = os.path.join(os.path.dirname(__file__), "price_log.csv")

# ─────────────────────────────────────────────────────────────────────────
# 2. FLIGHTAPI.IO HELPERS
# ─────────────────────────────────────────────────────────────────────────
def search_round_trip() -> dict:
    """Calls FlightAPI.io's round-trip endpoint. Costs 2 credits per call."""
    api_key = os.environ["FLIGHTAPI_KEY"]
    url = (
        f"https://api.flightapi.io/roundtrip/{api_key}/"
        f"{ORIGIN}/{DESTINATION}/{OUTBOUND_DATE}/{RETURN_DATE}/"
        f"{ADULTS}/{CHILDREN}/{INFANTS}/{TRAVEL_CLASS}/{CURRENCY}"
    )
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def build_carrier_lookup(data: dict) -> dict:
    """FlightAPI references carriers by numeric ID elsewhere in the response.
    This builds a {carrier_id: iata_code} map so we can check airlines."""
    lookup = {}
    for carrier in data.get("carriers", []):
        carrier_id = carrier.get("id")
        code = carrier.get("iata") or carrier.get("code") or carrier.get("name")
        if carrier_id is not None and code:
            lookup[carrier_id] = code
    return lookup


def build_leg_lookup(data: dict) -> dict:
    """Maps leg id -> leg details (stop_count, carrier ids)."""
    return {leg["id"]: leg for leg in data.get("legs", [])}


def leg_is_valid(leg: dict, carrier_lookup: dict, is_return: bool) -> bool:
    """
    A single direction (leg) is valid if:
      - nonstop (stop_count == 0) AND operated by El Al, OR
      - one-stop (stop_count == 1) AND the Israel-touching segment is
        on an Israeli airline.
    We approximate "Israel-touching carrier" using the leg's marketing
    carrier list, since FlightAPI's leg-level data doesn't always expose
    per-segment carrier order clearly — if ANY Israeli airline appears in
    the leg's marketing carriers for a one-stop itinerary, we treat it as
    a match and let you verify exact routing manually via the email link.
    """
    stop_count = leg.get("stop_count", 99)
    carrier_ids = leg.get("marketing_carrier_ids", [])
    codes = {carrier_lookup.get(cid, "") for cid in carrier_ids}

    if stop_count == 0:
        return NONSTOP_ONLY_AIRLINE in codes
    if stop_count == 1:
        return bool(codes & ISRAELI_AIRLINES)
    return False  # 2+ stops not acceptable


def parse_offers(data: dict) -> list[dict]:
    """Extract price + routing info from itineraries, keeping only those
    where BOTH outbound and return legs satisfy our Israeli-airline rule."""
    carrier_lookup = build_carrier_lookup(data)
    leg_lookup = build_leg_lookup(data)

    parsed = []
    for itinerary in data.get("itineraries", []):
        try:
            leg_ids = itinerary["leg_ids"]
            if len(leg_ids) < 2:
                continue  # need both outbound and return

            outbound_leg = leg_lookup.get(leg_ids[0])
            return_leg = leg_lookup.get(leg_ids[1])
            if not outbound_leg or not return_leg:
                continue

            if not leg_is_valid(outbound_leg, carrier_lookup, is_return=False):
                continue
            if not leg_is_valid(return_leg, carrier_lookup, is_return=True):
                continue

            price_info = itinerary.get("cheapest_price", {})
            price = float(price_info.get("amount"))

            def leg_summary(leg):
                codes = {carrier_lookup.get(cid, "?") for cid in leg.get("marketing_carrier_ids", [])}
                stops = leg.get("stop_count", "?")
                return f"{'+'.join(sorted(codes))} ({stops} stop{'s' if stops != 1 else ''})"

            parsed.append({
                "price": price,
                "currency": CURRENCY,
                "outbound_summary": leg_summary(outbound_leg),
                "return_summary": leg_summary(return_leg),
            })
        except (KeyError, ValueError, TypeError, IndexError):
            continue  # skip malformed entries rather than crash the whole run
    return parsed


# ─────────────────────────────────────────────────────────────────────────
# 3. LOGGING
# ─────────────────────────────────────────────────────────────────────────
def log_results(offers: list[dict]) -> None:
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "checked_at", "outbound", "return", "price", "currency", "cheaper_than_paid",
            ])
        for o in offers:
            cheaper = o["price"] < AMOUNT_PAID_USD
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                o["outbound_summary"],
                o["return_summary"],
                o["price"],
                o["currency"],
                cheaper,
            ])


# ─────────────────────────────────────────────────────────────────────────
# 4. EMAIL ALERT
# ─────────────────────────────────────────────────────────────────────────
def send_email_alert(subject: str, body: str) -> None:
    from_addr = os.environ["EMAIL_FROM"]
    app_password = os.environ["EMAIL_APP_PASSWORD"]
    to_addr = os.environ["EMAIL_TO"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


# ─────────────────────────────────────────────────────────────────────────
# 5. MAIN
# ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    today = date.today()

    if today > STOP_DATE:
        print(f"Today ({today}) is past the stop date ({STOP_DATE}). Nothing to do.")
        sys.exit(0)

    print(f"Checking Israeli-airline routes {ORIGIN} -> {DESTINATION}, "
          f"{OUTBOUND_DATE} to {RETURN_DATE}, {ADULTS} adults, {TRAVEL_CLASS}...")

    data = search_round_trip()
    offers = parse_offers(data)

    if not offers:
        print("No qualifying offers (El Al nonstop, or Israeli-airline one-stop) found today.")
        log_results([])
        return

    log_results(offers)

    cheaper_offers = [o for o in offers if o["price"] < AMOUNT_PAID_USD]

    if cheaper_offers:
        best = min(cheaper_offers, key=lambda o: o["price"])
        savings = AMOUNT_PAID_USD - best["price"]
        subject = f"✈️ Cheaper SFO option found: ${best['price']:.0f} (save ${savings:.0f})"
        body = (
            f"Found a cheaper qualifying option to reach SFO from TLV.\n\n"
            f"New price: {best['price']:.2f} {best['currency']}\n"
            f"You paid:  {AMOUNT_PAID_USD:.2f} {CURRENCY}\n"
            f"Potential savings: {savings:.2f} {CURRENCY}\n\n"
            f"Outbound: {best['outbound_summary']}\n"
            f"Return:   {best['return_summary']}\n\n"
            f"Outbound date: {OUTBOUND_DATE}   Return date: {RETURN_DATE}\n"
            f"Cabin: {TRAVEL_CLASS}   Adults: {ADULTS}\n\n"
            f"Rule applied: nonstop must be El Al; one-stop must involve an Israeli airline "
            f"on the Israel-touching leg. Please verify the exact routing and fare rules before "
            f"booking, and check any change/cancellation fees on your current ticket.\n"
        )
        send_email_alert(subject, body)
        print(f"ALERT SENT: qualifying fare found at {best['price']:.2f} {best['currency']}")
    else:
        cheapest_seen = min(offers, key=lambda o: o["price"])
        print(f"No cheaper qualifying fare today. Cheapest seen: "
              f"{cheapest_seen['price']:.2f} {cheapest_seen['currency']} — "
              f"out: {cheapest_seen['outbound_summary']} / back: {cheapest_seen['return_summary']}")


if __name__ == "__main__":
    main()
