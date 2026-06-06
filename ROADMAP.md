# PractiScore Neo — Roadmap

Planned features and open research tasks. Roughly ordered by priority.

---

## Commands

### `/help` command
- `/help` lists all available commands with a short description of each
- `/help [command]` gives detailed usage for a specific command (parameters, examples, behavior)

---

## Configuration

### Feature flags via config file
- Add a `features` section to `clubs.yaml` (or a separate config file) to enable/disable bot features
- Initial flag: `subscriptions` — lets server owners turn off the `/subscribe`, `/unsubscribe`, and `/mysubscriptions` commands and DM behavior if they don't want it

### Admin configuration via Discord slash commands
- Add slash commands so server admins can manage the bot without editing files or restarting:
  - `/config addclub <url>` — add a club to track
  - `/config removeclub <club>` — stop tracking a club
  - `/config setchannel <channel>` — set the announcements channel
  - `/config features` — view and toggle feature flags
- Requires role-based permission gating — only users with a designated admin role (or server admin) can use these commands

---

## Research

### Investigate PractiScore's internal API
- PractiScore has a REST API at `api.beta.practiscore.com` with a per-club endpoint (`/clubs/{slug}/matches`) and a general search endpoint (`/search/matches`)
- The API appears to use Firebase authentication — likely obtainable via Firebase anonymous auth (no real account needed)
- If this works: eliminates ScraperAPI entirely, no credits, no Cloudflare workaround
- **Action:** Test Firebase anonymous auth flow with PractiScore's Firebase API key to confirm the approach works end to end

### Investigate alternative scraping services
- Current setup: ScraperAPI free tier (1,000 credits/month) — already hitting the limit
- Zyte (formerly Splash/Scrapy Cloud) was recommended as a potentially cheaper option
- **Action:** Compare Zyte, ScraperAPI paid tiers, and any other residential proxy services on price per request and reliability against Cloudflare

---

## Future (depends on scraping cost)

### User-submitted clubs
- Allow non-admin Discord users to add their own clubs via a slash command
- Only viable if per-request scraping cost drops enough that open-ended club additions don't run up a large bill
- Will need a rate limit or approval flow to prevent abuse
- Blocked on: resolving scraping economics (API workaround or cheaper service)

---

## Completed

- [x] Match announcement notifications
- [x] Registration open notifications
- [x] Match cancellation detection
- [x] DM subscriptions (`/subscribe`, `/unsubscribe`, `/mysubscriptions`)
- [x] Slash commands: `/clubs`, `/matches`
- [x] Configurable scraping window and poll interval
- [x] Clubs configurable via `clubs.yaml` (names auto-fetched from PractiScore)
- [x] Published to GitHub as `practiscore-neo`
