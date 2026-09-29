# PractiScore Neo — Roadmap

The bot is now a personal, DM-only bot. Planned work, roughly in order.

---

## Exact registration times via PractiScore's search index

Club pages only give a rounded countdown ("opens in 1 week"), and match pages hide exact times behind a login. PractiScore's own match search is backed by an Algolia index whose records carry exact `reg_open_date` / `reg_close_date` values and the Open/Closed status.

- Phase 2: run an index reader beside the club-page scraper and log differences for a week, without alerting
- Phase 3, if the test holds up: use it for `standard` and `manual` clubs and `/scan`, schedule checks at exact registration times, and keep the club-page scraper as a fallback
- Failure checks: key capture failure, rejected key, schema changes, silently empty results, and daily disagreement with the club page

## `/findclub <name>`

Search PractiScore's club directory by name, with buttons to track the club or scan it once. Depends on the index reader above.

## Unverified registration labels

Labels for full matches, waitlists and registration closed by date haven't been seen yet. They're reported as unknown when they appear, and the parser gets extended then.

---

## Completed

- [x] Match announcement notifications
- [x] Registration open notifications
- [x] Slash commands: `/clubs`, `/matches`, `/help`, `/status`
- [x] Published to GitHub as `practiscore-neo`
- [x] Owner-only, DM-only bot (2026-09)
- [x] Club tiers: watched, standard, manual, paused
- [x] Match levels (starred, normal, muted) with DM buttons and per-club rules
- [x] Registration closed-again, reopened and date-change alerts
- [x] Removal detection from the club listing (replaced a 404 check that could never fire)
- [x] Checks scheduled around "opens in N hours", including overnight
- [x] `/scraping on|off`, `/addclub`, `/removeclub`, `/tier`, `/scan`, `/star`, `/unstar`, `/mute`, `/rule`
- [x] Failure alert state stored in the database, so restarts don't re-arm it
