import discord

STATE_ICONS = {"open": "🟢", "not_yet": "⏳", "closed": "🔒", "unknown": "❔"}
STATE_NAMES = {"open": "Open", "not_yet": "Not yet open", "closed": "Closed", "unknown": "Unknown"}
LEVEL_ICONS = {"starred": "⭐", "normal": "", "muted": "🔇"}

GREY = discord.Color(0x777777)
ORANGE = discord.Color.orange()

# kind -> (author line, colour)
EVENT_STYLES = {
    "new": ("New Match Posted", GREY),
    "opened": ("Registration Now Open", discord.Color.green()),
    "reopened": ("Registration Reopened", discord.Color.green()),
    "closed": ("Registration Closed", ORANGE),
    "date_changed": ("Match Date Changed", discord.Color.blue()),
    "removed": ("Match Removed from Listing", discord.Color.red()),
    "relisted": ("Match Back on Listing", discord.Color.blue()),
    "unknown_label": ("Unrecognized Registration Label", discord.Color.gold()),
}


def registration_text(match) -> str:
    state = match.get("reg_state") or "unknown"
    label = match.get("label_text") or ""
    if state == "not_yet" and label:
        return f"{STATE_ICONS[state]} {label[0].upper()}{label[1:]}"
    return f"{STATE_ICONS[state]} {STATE_NAMES[state]}"


def event_embed(event, club_name):
    """One embed per alert. `event` is a monitor.Event."""
    match = event.match
    author, color = EVENT_STYLES[event.kind]
    if event.kind == "new" and match.get("reg_state") == "open":
        author, color = "New Match — Registration ALREADY OPEN", discord.Color.green()
    if event.kind == "closed" and event.old.get("reg_state") == "open":
        author = "Registration Closed Again"

    embed = discord.Embed(
        title=match["title"],
        url=None if event.kind == "removed" else match.get("url") or None,
        description=club_name,
        color=color,
    )
    embed.set_author(name=author)
    if event.kind == "date_changed":
        embed.add_field(name="Date", value=f"~~{event.old['date']}~~ → **{match['date']}**", inline=True)
    else:
        embed.add_field(name="Date", value=match.get("date") or "TBD", inline=True)
    if match.get("match_type"):
        embed.add_field(name="Type", value=match["match_type"], inline=True)
    if event.kind != "removed":
        embed.add_field(name="Registration", value=registration_text(match), inline=True)

    if event.kind == "removed":
        embed.set_footer(text="Missing from the club page on 2 checks in a row — cancelled or deleted. "
                              "Verify with the club.")
    elif event.kind == "unknown_label":
        embed.set_footer(text=f"The label reads \"{match.get('label_text')}\". The bot can't tell whether "
                              "registration is open, so check the match page.")
    elif event.kind == "new":
        embed.set_footer(text=f"Level: {event.level}. Use the buttons to change it.")
    return embed


def summary_embed(title, club_name, matches, note=None):
    """Compact list of matches — used for new clubs, resumed clubs and /scan."""
    lines = []
    for m in matches:
        icon = LEVEL_ICONS.get(m.get("level") or "normal", "")
        name = f"[{m['title']}]({m['url']})" if m.get("url") else m["title"]
        lines.append(f"{icon}{' ' if icon else ''}**{name}**\n{m.get('date') or 'TBD'} · {registration_text(m)}")
    description = "\n\n".join(lines) if lines else "No upcoming matches listed."
    if len(description) > 3900:
        kept, total = [], 0
        for line in lines:
            if total + len(line) > 3800:
                break
            kept.append(line)
            total += len(line) + 2
        description = "\n\n".join(kept) + f"\n\n…and {len(lines) - len(kept)} more"
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    embed.set_author(name=club_name)
    if note:
        embed.set_footer(text=note)
    return embed


def scrape_failure_embed(failures, consecutive, last_success):
    embed = discord.Embed(
        title="Scraping is failing",
        description=(
            f"The last **{consecutive}** checks failed for every club they covered. "
            "New matches and registration openings are not being detected."
        ),
        color=discord.Color.red(),
    )
    embed.set_author(name="PractiScore Neo — Alert")
    for name, error in failures[:5]:
        embed.add_field(name=name, value=f"```{error[:300]}```", inline=False)
    embed.add_field(
        name="Last successful check",
        value=(
            last_success.strftime("%b %d, %Y at %I:%M %p %Z")
            if last_success
            else "None recorded"
        ),
        inline=False,
    )
    embed.set_footer(text="You'll get one more DM when scraping recovers.")
    return embed


def scrape_recovered_embed(failed_checks, recovered_at):
    embed = discord.Embed(
        title="Scraping recovered",
        description=f"Scraping is working again after {failed_checks} failed checks.",
        color=discord.Color.green(),
    )
    embed.set_author(name="PractiScore Neo — Alert")
    embed.add_field(
        name="Recovered at",
        value=recovered_at.strftime("%b %d, %Y at %I:%M %p %Z"),
        inline=False,
    )
    return embed


def _usage_color(pct):
    if pct >= 80:
        return discord.Color.red()
    if pct >= 50:
        return ORANGE
    return discord.Color.green()


def _ts(dt, style="f"):
    return f"<t:{int(dt.timestamp())}:{style}>"


def usage_embed(usage, cap, projected):
    """`usage` is a zyte_usage.Usage; `projected` is the projected period spend or None."""
    pct = usage.cost_usd / cap * 100 if cap else 0
    embed = discord.Embed(title="Zyte API usage", color=_usage_color(pct))
    embed.add_field(
        name="This billing period",
        value=f"**${usage.cost_usd:.2f}** of ${cap:.0f} ({pct:.1f}%)\n"
              f"{_ts(usage.period_start, 'D')} → {_ts(usage.period_end, 'D')} (resets {_ts(usage.period_end, 'R')})",
        inline=False,
    )
    requests_line = f"{usage.requests:,}"
    if usage.requests:
        requests_line += f" · ${usage.cost_usd / usage.requests * 1000:.2f} per 1,000"
        if usage.failed:
            requests_line += f"\n{usage.failed:,} failed ({usage.failed / usage.requests:.0%})"
    embed.add_field(name="Requests", value=requests_line, inline=True)
    embed.add_field(
        name="Projected",
        value=f"${projected:.2f} by reset" if projected is not None else "After the first day",
        inline=True,
    )
    recent = usage.days[-7:]
    if recent:
        embed.add_field(
            name="Recent days (UTC)",
            value="\n".join(f"{day:%b %d} — {n:,} req · ${cost:.2f}" for day, n, cost in reversed(recent)),
            inline=False,
        )
    embed.set_footer(text="From the Zyte Stats API; the period is assumed to roll over at midnight UTC.")
    return embed


def usage_alert_embed(usage, cap, threshold, projected):
    embed = usage_embed(usage, cap, projected)
    embed.title = f"Zyte spend passed {threshold}% of the monthly cap"
    embed.set_author(name="PractiScore Neo — Alert")
    embed.description = ("At the cap, Zyte suspends the account and scraping stops until "
                         f"{_ts(usage.period_end, 'D')}.")
    return embed
