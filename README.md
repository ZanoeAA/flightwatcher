[README (1).md](https://github.com/user-attachments/files/31405798/README.1.md)
# Flight Price Watcher — TLV → SFO (Premium Economy)

Checks every 10 days for a cheaper way to reach SFO from TLV, under this
rule: the trip must be either nonstop on El Al, or one-stop where the
Israel-touching leg is on an Israeli airline (El Al, Arkia, or Israir).
Applies to both outbound and return. Emails you if it finds a qualifying
option cheaper than what you paid. Stops automatically 3 days before
departure (Dec 1, 2026).

Runs for free on GitHub Actions, so it works even when your laptop is off.
Alerts arrive by email, which you'll see on your laptop, iPhone, and iPad
automatically — no extra app needed.

---

## A note on why this uses FlightAPI.io, not Amadeus

Amadeus shut down its free self-service developer portal on July 17, 2026
— it now only serves paying enterprise customers. FlightAPI.io is the
closest working free alternative, but its free tier is limited to roughly
20-30 credits total, and each price check costs 2 credits. That's why this
script is set up to run every 10 days rather than daily — at that pace,
your free credits comfortably last through your December 4 departure.

## 1. Get a FlightAPI.io API key (free)

1. Go to https://api.flightapi.io/register and sign up — no credit card
   required.
2. After registering, your API key will be shown on your Dashboard. Copy
   it somewhere safe — this is your `FLIGHTAPI_KEY`.

## 2. Set up a Gmail "app password" for sending alerts

Regular Gmail passwords won't work for this — Google requires a special
16-character "app password" for scripts.

1. Turn on 2-Step Verification on your Google account, if not already on:
   https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create a new app password (name it "flight-watcher"). Copy the 16-character
   code — this is your `EMAIL_APP_PASSWORD`.
4. `EMAIL_FROM` is that same Gmail address. `EMAIL_TO` can be the same
   address, or any other inbox you check on your phone.

## 3. Put this project on GitHub (already done if you're following along)

Your private repo should already contain:
- `flight_watcher.py`
- `requirements.txt`
- `README.md`
- `.github/workflows/daily-check.yml`

## 4. Add your secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these one at a time:

| Secret name              | Value                                  |
|---------------------------|-----------------------------------------|
| `FLIGHTAPI_KEY`           | from step 1                             |
| `EMAIL_FROM`              | your Gmail address                      |
| `EMAIL_APP_PASSWORD`      | 16-character app password from step 2   |
| `EMAIL_TO`                | where you want alerts sent              |

Note: if you already added `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET`
secrets earlier, you can leave them (they're just unused) or delete them
from the same Settings page — either is fine.

## 5. Done

The workflow now runs automatically roughly every 10 days (1st, 11th, and
21st of each month at 07:00 UTC). You can also trigger it manually any
time from the **Actions** tab in your repo → "Flight Price Check (every
10 days)" → **Run workflow**.

Every run also appends a row to `price_log.csv` in the repo (viewable on
GitHub from any device) so you can see the price history even on days you
don't get an email.

---

## Trip details currently configured

- Route: Tel Aviv (TLV) → San Francisco (SFO)
- Outbound: December 4, 2026
- Return: December 21, 2026
- Passengers: 2 adults
- Cabin: Premium Economy
- Qualifying routing rule (applied to BOTH outbound and return):
  - Nonstop → must be El Al (LY)
  - One-stop → the Israel-touching leg must be an Israeli airline: El Al (LY), Arkia (IZ), or Israir (6H)
  - Anything with 2+ stops is ignored
- Amount paid (comparison baseline): $7,650 USD total — this reflects what
  you paid for your current TLV↔LAX El Al ticket plus the free United-miles
  LAX↔SFO hop, since reaching SFO is the actual goal
- Stops checking: December 1, 2026 (3 days before departure)
- Check frequency: every ~10 days (to stay within FlightAPI.io's free credit limit)

If any of these change, edit the constants at the top of `flight_watcher.py`.

## A note on accuracy

FlightAPI.io aggregates fares from many online travel agencies (OTAs), not
just airlines directly. When it finds a qualifying cheaper option, always
click through and verify the exact routing, fare rules, and any hidden fees
before booking — treat the email alert as a lead to investigate, not a
guaranteed bookable price.
