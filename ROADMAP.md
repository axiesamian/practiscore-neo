# PractiScore Neo — Roadmap

Planned features and open research tasks. Roughly ordered by priority.

---

## Commands

### Feedback and bug reporting
- Allow users to submit feedback or bug reports from within Discord via a slash command
- Report should be routed somewhere actionable (private channel, DM to admin, or GitHub issue)

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
