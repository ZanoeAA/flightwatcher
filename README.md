# Flight Price Watcher — TLV → San Francisco Bay Area (Premium Economy)

Checks daily for a cheaper way to reach SFO (preferred) or OAK from TLV,
under this rule: the trip must be either nonstop on El Al, or one-stop
where the first leg out of TLV departs on an Israeli airline (El Al,
Arkia, or Israir). Applies the same rule to both outbound and return.
Emails you if it finds a qualifying option cheaper than what you paid.
Stops automatically 3 days before departure (Dec 1, 2026).

Runs for free on GitHub Actions, so it works even when your laptop is off.
Alerts arrive by email, which you'll see on your laptop, iPhone, and iPad
automatically — no extra app needed.

---

## 1. Get an Amadeus API key (free)

1. Go to https://developers.amadeus.com and create a free account.
2. Click **My Self-Service Workspace → Create New App**.
3. Name it anything (e.g. "flight-watcher"). You'll get:
   - an **API Key** → this is your `AMADEUS_CLIENT_ID`
   - an **API Secret** → this is your `AMADEUS_CLIENT_SECRET`
4. The free "test" tier is enough to run daily checks. (Its data can lag
   slightly behind live prices — if you want fully live pricing later, apply
   for the free "production" tier and change one URL in the script — see the
   comment above `AMADEUS_BASE_URL` in `flight_watcher.py`.)

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

## 3. Put this project on GitHub (free, private repo is fine)

1. Create a new **private** repository on GitHub.
2. Upload all files in this folder (`flight_watcher.py`, `requirements.txt`,
   `.github/workflows/daily-check.yml`) to it — either by dragging them into
   the GitHub web UI, or via `git push` if you're comfortable with git.

## 4. Add your secrets to GitHub

In your new repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these one at a time:

| Secret name              | Value                                  |
|---------------------------|-----------------------------------------|
| `AMADEUS_CLIENT_ID`       | from step 1                             |
| `AMADEUS_CLIENT_SECRET`   | from step 1                             |
| `EMAIL_FROM`              | your Gmail address                      |
| `EMAIL_APP_PASSWORD`      | 16-character app password from step 2   |
| `EMAIL_TO`                | where you want alerts sent              |

## 5. Done

The workflow (`.github/workflows/daily-check.yml`) will now run automatically
every day at 07:00 UTC. You can also trigger it manually any time from the
**Actions** tab in your repo → "Daily Flight Price Check" → **Run workflow**.

Every run also appends a row to `price_log.csv` in the repo (viewable on
GitHub from any device) so you can see the price history even on days you
don't get an email.

---

## Trip details currently configured

- Route: Tel Aviv (TLV) → San Francisco (SFO preferred, OAK acceptable)
- Outbound: December 4, 2026
- Return: December 21, 2026
- Passengers: 2 adults
- Cabin: Premium Economy
- Qualifying routing rule (applied to BOTH outbound and return):
  - Nonstop → must be El Al (LY)
  - One-stop → first leg out of TLV must be an Israeli airline: El Al (LY), Arkia (IZ), or Israir (6H)
  - Anything with 2+ stops, or a non-Israeli first leg, is ignored
- Amount paid (comparison baseline): $7,650 USD total — this reflects what
  you paid for your current TLV↔LAX El Al ticket plus the free United-miles
  LAX↔SFO hop, since reaching the SF Bay Area is the actual goal
- Stops checking: December 1, 2026 (3 days before departure)

If any of these change, edit the constants at the top of `flight_watcher.py`.

## How this differs from a simple "same flight, lower price" watcher

This isn't just re-checking your exact TLV-LAX El Al flight. It searches
broadly for *any* way to reach SFO/OAK that satisfies the Israeli-airline
rule — including one-stop itineraries via Arkia or Israir — and compares
the total price against what you're currently paying to get to SF (LAX
fare + implicit value of reaching SF). If a genuinely cheaper qualifying
option turns up, you'll get an email with the routing details so you can
compare it against your existing ticket (including any change fees).
