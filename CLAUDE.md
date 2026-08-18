# Truck Driver Assignment — Full Stack Dev Assessment

## Assignment Spec

**Stack**: Django (backend) + React (frontend).

**Deliverables**:
- Live hosted version (Vercel.app ok for frontend; backend needs its own host, e.g. Render/Railway/Fly)
- 3-5 min Loom walking through app + code
- Github repo (public/shared)
- Reward: $100
- Graded on: accuracy of output (tested against hosted version) + UI/UX polish (good design can offset minor accuracy gaps)

**Inputs** (from user):
1. Current location
2. Pickup location
3. Dropoff location
4. Current Cycle Used (Hrs) — hours already accumulated in the driver's 70hr/8-day cycle

**Outputs**:
1. **Map** — route + stops/rests, using a free map API (e.g. OpenRouteService, OSRM, Mapbox free tier, Leaflet + OSM)
2. **Daily Log Sheets** — drawn/filled ELD-style grid, one sheet per 24hr period; multiple sheets for multi-day trips

**Assumptions to hardcode**:
- Property-carrying driver, 70hrs/8-day cycle (not 60/7)
- No adverse driving conditions (skip that exception entirely)
- Fuel stop at least once every 1,000 miles
- 1 hour each for pickup and dropoff (counts as on-duty, not-driving)

## HOS Rules Reference (49 CFR Part 395 — Property-Carrying CMVs)

Source: FMCSA "Interstate Truck Driver's Guide to Hours of Service" (April 2022).

### Core Duty Limits (all three apply simultaneously)

1. **14-Hour Driving Window** (§395.3(a)(2))
   - 14 consecutive hours to complete all driving, starting from when driver begins ANY work (on-duty or driving).
   - Window does NOT pause for breaks/meals/fuel — it just keeps running once started.
   - Once 14 hrs elapsed from start-of-shift, no more driving allowed (non-driving on-duty work still ok) until 10 consecutive hrs off duty taken.
   - Example: 10 hrs off, start work 6:00am → last legal driving moment is 8:00pm (14 hrs later). Other (non-driving) work still allowed after 8:00pm, but no more driving until another 10 consecutive hrs off (or equivalent).

2. **11-Hour Driving Limit** (§395.3(a)(3))
   - Max 11 hours actual driving time within the 14-hr window.
   - Driving also not permitted if more than 8 hrs have passed since the end of the last qualifying 30-min break (see rule 3 below).
   - After 11 hrs driving, must take 10 consecutive hrs off before driving again.
   - Example: 10 hrs off, start 6:00am, drive 7:00am–2:00pm (7 hrs), take required 30-min break, drive 4 more hrs to 6:30pm (11 hrs total driving). Other work allowed after 6:30pm; no more driving until 10 consecutive hrs off.

3. **30-Minute Break Rule** (§395.3(a)(3)(ii))
   - Required after 8 cumulative hours of driving (not consecutive — cumulative since last qualifying break).
   - Break can be off-duty, on-duty-not-driving, or sleeper berth — just needs to be 30 consecutive minutes.
   - Can be composed of normal work interruptions (loading/unloading, paperwork, fueling) as long as the pieces are consecutive — e.g. 15 min on-duty-not-driving + 15 min off-duty back-to-back satisfies it. Short, non-consecutive periods CANNOT be combined to reach 30 min.
   - Does not increase max driving time for the shift, and does not allow driving after the 14th hour from shift start — i.e. does not extend the 14-hr window or 11-hr driving limit.
   - Not applicable to drivers using either short-haul exception (§395.1(e)(1) or (e)(2)) — not relevant here, assignment has no short-haul exception.

4. **60/70-Hour On-Duty Limit** (§395.3(b)) — **use 70hr/8-day per assignment**
   - Based on a rolling/floating 7- or 8-day period (NOT a fixed calendar week), starting at the time the carrier designates for the 24-hr period start. Applies in addition to the 14-hr and 11-hr limits.
   - Total on-duty time (driving + non-driving), not just driving.
   - Oldest day's hours drop off at the end of each day as the rolling total is recalculated.
   - Cannot drive once 70 hrs reached in that rolling window; other (non-driving) work still allowed.
   - Violations of the 60/7 or 70/8 rule can only occur by DRIVING past the limit — remaining on-duty-not-driving past the limit is not itself a violation.
   - Any 34 consecutive hrs off duty resets the rolling 60/7 or 70/8 total back to zero (see 34-Hour Restart below).
   - Example (70/8): Days 1–8 total 67 on-duty hrs → compliant. On Day 9 (second Monday), Day 1's hours drop off; recalculating Days 2–9 gives 73 hrs — would be a violation if driving occurred in the last 3 hrs over 70. On Day 10, no new on-duty hours accrued; recalculating Days 3–10 gives 63 hrs — back in compliance.

   Underlying daily hours for that example:

   | Day # | Day | Hours |
   |---|---|---|
   | 1 | Sunday | 0 |
   | 2 | Monday | 10 |
   | 3 | Tuesday | 8.5 |
   | 4 | Wednesday | 12.5 |
   | 5 | Thursday | 9 |
   | 6 | Friday | 10 |
   | 7 | Saturday | 12 |
   | 8 | Sunday | 5 |
   | 9 | Monday | 6 |
   | 10 | Tuesday | 0 |

   Rolling windows: Days 1-8 = 67 hrs · Days 2-9 = 73 hrs · Days 3-10 = 63 hrs.

   This app always uses **70-hour/8-day** per the assignment's stated assumptions (the 60-hr/7-day alternate schedule in §395.3(b) is not implemented).

### Off-Duty / Reset Rules

5. **10 Consecutive Hours Off Duty** — required to reset the 14-hr window and 11-hr driving clock.

6. **34-Hour Restart** (§395.3(c)(1)-(2))
   - Taking 34+ consecutive hours off duty resets the 70-hr/8-day accumulator to zero.
   - Optional, not mandatory. Use in planning logic when the 70-hr limit would otherwise block the trip.
   - Example: driver works 14 hrs/day for 5 straight days → hits 70 hrs, can't drive again until dropping below 70 in the rolling 8-day window. If the 34-hr restart is used instead, driving time is available immediately after 34 consecutive hrs off duty, and a fresh 8-day/70-hr period begins.

*(Sleeper berth split provisions, team-driver passenger-seat rules, and the 60-hr/7-day alternate schedule are out of scope — this app is single-driver, 70/8 only, and does not model sleeper berth splitting. See the source PDF if that scope changes.)*

### On-Duty vs Off-Duty (§395.2) — what counts toward the 14-hr window and 70-hr cycle

On-duty = all driving time, plus all other time working for the carrier (loading/unloading, fueling, paperwork, inspections, waiting to be dispatched). Off-duty = fully relieved of duty, free to leave, doing no paid work for anyone.

For this app, only 4 statuses matter (matches the log grid): **Off Duty**, **Sleeper Berth** (used only for the mandatory 10-hr/34-hr rest blocks the algorithm inserts, not for split-sleeper logic), **Driving**, **On Duty (Not Driving)** (pickup, dropoff, fuel stops).

### Assumptions Baked Into This App (per assignment)

- **No adverse driving conditions exception** — do not add the +2hr driving / +2hr window extension logic.
- **Fueling every 1,000 miles** — insert a fuel stop (treat as on-duty-not-driving, ~30-60 min) whenever cumulative route distance crosses a 1,000-mile increment.
- **1 hr pickup + 1 hr dropoff** — both logged as on-duty, not-driving, at trip start (pickup) and trip end (dropoff).
- **Property-carrying, 70hr/8-day schedule** — always use 70/8 math, never 60/7.

### Trip Planning Algorithm (implied by rules above)

1. Compute route + total distance/duration via map API (current → pickup → dropoff).
2. Start clock: on-duty begins at pickup (1 hr on-duty-not-driving for pickup).
3. Drive in segments, capped by: 11 hrs driving/day, 14 hr window/day, 30-min break after 8 cumulative driving hrs, 70-hr/8-day rolling total (input via "Current Cycle Used (Hrs)").
4. Insert fuel stops every 1,000 miles (on-duty-not-driving).
5. When 11-hr driving or 14-hr window limit hit: insert 10-consecutive-hour off-duty period (new calendar day / new log sheet starts).
6. If 70-hr cycle limit would be exceeded and trip still incomplete: insert 34-hr restart before resuming.
7. At dropoff: add 1 hr on-duty-not-driving.
8. Generate one Daily Log Sheet (24-hr grid) per calendar day spanned by the above.

### Daily Log Sheet — Required Fields & Layout

Must replicate the standard FMCSA grid (see `blank-paper-log.png` in this dir):

**Header fields**:
- Date (month/day/year) for the beginning of the 24-hr period — multiple consecutive off-duty days may be combined on one log page, with an explanation in Remarks
- Total miles driving today
- Total mileage today (odometer, optional if not tracked)
- Truck/tractor and trailer number(s) — vehicle number(s) assigned by carrier, or license number + licensing state, for each truck/trailer driven that period
- Name of carrier(s) — if working for >1 carrier in the 24-hr period, list start/end times per carrier
- Main office address (city + state sufficient)
- Driver's signature/certification ("I certify these entries are true and correct") — legal name or name of record
- Name of co-driver (if any)
- Time base: use the home terminal's time zone consistently, even when crossing time zones during the trip; all drivers from the same home terminal use the same 24-hr period start time, as designated by the employer

**Graph grid** (24-hr, hourly increments, midnight-to-midnight):
- 4 duty-status rows, each drawn as a horizontal line segment for the time span in that status:
  1. Off Duty
  2. Sleeper Berth
  3. Driving
  4. On Duty (Not Driving) — also includes time driving a non-CMV vehicle for the carrier (e.g. a company car)
- Total hours per row must sum to 24 (unless the page combines multiple consecutive off-duty days).
- Grid must stay current to the driver's last duty-status change — e.g. if stopped mid-drive, the final entry on the log should reflect the time/place driving last started (matches what a roadside inspector would check).
- Other required header/remarks info can be placed anywhere outside the grid itself.

**Remarks section**:
- City/town/state (or highway+milepost / highway+service plaza / two nearest cross-highways + nearest city/state) logged at EVERY duty-status change.
- Optional notes: adverse conditions, state-line crossings, shipping info.

**Recap boxes** (bottom of sheet, per 70/8-day schedule since that's what this app uses):
- On-duty hours today (from lines 3+4)
- A. Total hours on duty last 7 days including today
- B. Total hours available tomorrow (70 minus A)
- C. Total hours on duty last 8 days including today, if a 34-hr restart were taken (recap for "hours available if restarted")
- "If you took 34 consecutive hours off you have 60/70 hours available" note box

**Multi-day trips**: generate one grid page per 24-hr period spanned; carry over remaining driving/duty hours across pages; last duty-status entry on a page should reflect where the driver actually was (per the guide's inspector example).

**Key point** (from the guide's worked example): a driver can be on-duty past the 14th hour of the shift — that's fine, as long as NO driving happens after the 14th hour. Only driving is capped by the 14-hr window; other on-duty work (paperwork, post-trip inspection) can continue. Useful for validating the algorithm's output logs.

### Reference Files in This Directory
- `new-full-stack-dev-assessment.docx` — original assignment brief
- `fmcsa-hos-395-drivers-guide-to-hos-2022-04-28-0-1-.pdf` — full FMCSA HOS guide (27 pages), source for all rules above
- `blank-paper-log.png` — blank daily log grid template to match visually
- `fmsca-image.png` — HOS guide table of contents (context only)

### Exceptions Not Implemented

Assignment specifies no adverse conditions, no short-haul, no specialty cargo — none of the 49 CFR Part 395 exceptions (adverse driving, short-haul, agricultural, Alaska, construction, oilfield, utility, movie/TV, school bus, government, emergency-relief, etc.) apply. Full list in the source PDF (`fmcsa-hos-395-drivers-guide-to-hos-2022-04-28-0-1-.pdf`, Appendix A) if scope ever expands.
