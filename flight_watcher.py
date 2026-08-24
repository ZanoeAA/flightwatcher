#!/usr/bin/env python3
"""
Flight Price Watcher — TLV to San Francisco Bay Area
=======================================================
Goal: reach SFO (preferred) or OAK from TLV, where every alternative must be
either:
  (a) NONSTOP on El Al, or
  (b) ONE-STOP where the first leg departs TLV on an Israeli airline
      (El Al, Arkia, or Israir).

This mirrors your actual booking: TLV -> LAX on El Al, then a free
United-miles hop LAX -> SFO. We're watching for a genuinely better way to
get to the SF Bay Area under the same "Israeli airline out of TLV" rule.

Checks both directions (outbound TLV->SF-area and return SF-area->TLV) and
alerts you by email if it finds a valid alternative cheaper than what you
paid. Run this once a day (via cron or GitHub Actions — see README.md).
It automatically stops searching once STOP_DATE has passed.

All secrets are read from environment variables — never hard-code them:
    AMADEUS_CLIENT_ID
    AMADEUS_CLIENT_SECRET
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

# Preference order matters: SFO checked first; OAK accepted as a fallback.
DESTINATION_AIRPORTS = ["SFO", "OAK"]

OUTBOUND_DATE = "2026-12-04"
RETURN_DATE = "2026-12-21"
ADULTS = 2
TRAVEL_CLASS = "PREMIUM_ECONOMY"
CURRENCY = "USD"

# Israeli airlines — the FIRST leg out of TLV must be one of these.
# El Al is also the only one allowed to operate the WHOLE nonstop trip.
ISRAELI_AIRLINES = {
    "LY": "El Al",
    "IZ": "Arkia",
    "6H": "Israir",
}
NONSTOP_ONLY_AIRLINE = "LY"  # El Al is the only nonstop TLV-SF option

AMOUNT_PAID_USD = 7650.00   # total you paid for both adults, round trip (incl. the free LAX-SFO miles hop)

# Stop searching this many days before departure
DAYS_BEFORE_DEPARTURE_TO_STOP = 3
STOP_DATE = date(2026, 12, 1)   # Dec 4 minus 3 days, computed for clarity/safety

LOG_FILE = os.path.join(os.path.dirname(__file__), "price_log.csv")

# ─────────────────────────────────────────────────────────────────────────
# 2. AMADEUS API HELPERS
# ─────────────────────────────────────────────────────────────────────────
AMADEUS_BASE_URL = "https://test.api.amadeus.com"  # switch to api.amadeus.com after production approval


def get_amadeus_token() -> str:
    client_id = os.environ["AMADEUS_CLIENT_ID"]
    client_secret = os.environ["AMADEUS_CLIENT_SECRET"]

    resp = requests.post(
        f"{AMADEUS_BASE_URL}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_flights(token: str, destination: str) -> list[dict]:
    """Query Amadeus for offers to a given destination airport.
    Deliberately does NOT restrict to nonstop only, since one-stop
    itineraries are allowed as long as the first leg is Israeli-operated.
    """
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": ORIGIN,
        "destinationLocationCode": destination,
        "departureDate": OUTBOUND_DATE,
        "returnDate": RETURN_DATE,
        "adults": ADULTS,
        "travelClass": TRAVEL_CLASS,
        "currencyCode": CURRENCY,
        "max": 50,
    }
    resp = requests.get(
        f"{AMADEUS_BASE_URL}/v2/shopping/flight-offers",
        headers=headers,
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def itinerary_is_valid(segments: list[dict], is_return: bool) -> bool:
    """
    A single direction is valid if:
      - it's nonstop AND operated by El Al, OR
      - it's one-stop AND the leg touching Israel is on an Israeli airline.
        On the outbound (TLV -> SF-area), that's the FIRST segment
        (departing TLV). On the return (SF-area -> TLV), that's the LAST
        segment (landing in TLV) — the connecting leg in between can be
        any carrier.
    Anything with 2+ stops is rejected.
    """
    if len(segments) == 1:
        return segments[0]["carrierCode"] == NONSTOP_ONLY_AIRLINE
    if len(segments) == 2:
        israel_facing_segment = segments[-1] if is_return else segments[0]
        return israel_facing_segment["carrierCode"] in ISRAELI_AIRLINES
    return False  # 2+ stops not acceptable


def parse_offers(offers: list[dict], destination: str) -> list[dict]:
    """Extract price + per-direction routing info from each raw offer,
    keeping only offers where BOTH directions satisfy our rule."""
    parsed = []
    for offer in offers:
        try:
            itineraries = offer["itineraries"]
            if len(itineraries) < 2:
                continue  # need both outbound and return present

            outbound_segments = itineraries[0]["segments"]
            return_segments = itineraries[1]["segments"]

            if not itinerary_is_valid(outbound_segments, is_return=False):
                continue
            if not itinerary_is_valid(return_segments, is_return=True):
                continue

            price = float(offer["price"]["total"])
            currency = offer["price"]["currency"]

            def carriers_str(segments):
                return "+".join(s["carrierCode"] for s in segments)

            parsed.append({
                "destination": destination,
                "price": price,
                "currency": currency,
                "outbound_carriers": carriers_str(outbound_segments),
                "return_carriers": carriers_str(return_segments),
                "outbound_stops": len(outbound_segments) - 1,
                "return_stops": len(return_segments) - 1,
            })
        except (KeyError, ValueError, TypeError, IndexError):
            continue  # skip malformed offers rather than crash the whole run
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
                "checked_at", "destination", "outbound_carriers", "outbound_stops",
                "return_carriers", "return_stops", "price", "currency", "cheaper_than_paid",
            ])
        for o in offers:
            cheaper = o["price"] < AMOUNT_PAID_USD
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                o["destination"],
                o["outbound_carriers"],
                o["outbound_stops"],
                o["return_carriers"],
                o["return_stops"],
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
def describe_routing(o: dict) -> str:
    def leg_desc(carriers: str, stops: int) -> str:
        return f"{carriers} ({'nonstop' if stops == 0 else f'{stops}-stop'})"

    return (f"Outbound: {leg_desc(o['outbound_carriers'], o['outbound_stops'])} | "
            f"Return: {leg_desc(o['return_carriers'], o['return_stops'])}")


def main() -> None:
    today = date.today()

    if today > STOP_DATE:
        print(f"Today ({today}) is past the stop date ({STOP_DATE}). Nothing to do.")
        sys.exit(0)

    print(f"Checking Israeli-airline routes TLV -> {'/'.join(DESTINATION_AIRPORTS)}, "
          f"{OUTBOUND_DATE} to {RETURN_DATE}, {ADULTS} adults, {TRAVEL_CLASS}...")

    token = get_amadeus_token()

    all_valid_offers = []
    for dest in DESTINATION_AIRPORTS:
        raw_offers = search_flights(token, dest)
        valid = parse_offers(raw_offers, dest)
        print(f"  {dest}: {len(raw_offers)} raw offers, {len(valid)} match the Israeli-airline rule")
        all_valid_offers.extend(valid)

    if not all_valid_offers:
        print("No qualifying offers (El Al nonstop, or Israeli-first-leg one-stop) found today.")
        log_results([])
        return

    log_results(all_valid_offers)

    cheaper_offers = [o for o in all_valid_offers if o["price"] < AMOUNT_PAID_USD]

    if cheaper_offers:
        # Prefer SFO over OAK when prices are close; otherwise just take cheapest.
        best = min(cheaper_offers, key=lambda o: (o["price"], DESTINATION_AIRPORTS.index(o["destination"])))
        savings = AMOUNT_PAID_USD - best["price"]
        subject = f"✈️ Cheaper SF-area option found: ${best['price']:.0f} (save ${savings:.0f})"
        body = (
            f"Found a cheaper qualifying option to reach the SF Bay Area from TLV.\n\n"
            f"Destination airport: {best['destination']}\n"
            f"New price: {best['price']:.2f} {best['currency']}\n"
            f"You paid:  {AMOUNT_PAID_USD:.2f} {CURRENCY}\n"
            f"Potential savings: {savings:.2f} {CURRENCY}\n\n"
            f"{describe_routing(best)}\n\n"
            f"Outbound date: {OUTBOUND_DATE}   Return date: {RETURN_DATE}\n"
            f"Cabin: {TRAVEL_CLASS}   Adults: {ADULTS}\n\n"
            f"Rule applied: nonstop must be El Al; one-stop must depart TLV on an Israeli airline.\n"
            f"Verify fare rules and any change/cancellation fees on your current ticket before switching.\n"
        )
        send_email_alert(subject, body)
        print(f"ALERT SENT: {best['destination']} at {best['price']:.2f} {best['currency']}")
    else:
        cheapest_seen = min(all_valid_offers, key=lambda o: o["price"])
        print(f"No cheaper qualifying fare today. Cheapest seen: {cheapest_seen['destination']} "
              f"at {cheapest_seen['price']:.2f} {cheapest_seen['currency']} — {describe_routing(cheapest_seen)}")


if __name__ == "__main__":
    main()
