import discord


def new_match_embed(match, club_name):
    embed = discord.Embed(
        title=match["title"],
        url=match["url"],
        description=club_name,
        color=discord.Color(0x777777),
    )
    embed.set_author(name="New Match Posted")
    embed.add_field(name="Date", value=match["date"] or "TBD", inline=True)
    if match["match_type"]:
        embed.add_field(name="Type", value=match["match_type"], inline=True)
    return embed


def registration_open_embed(match, club_name):
    embed = discord.Embed(
        title=match["title"],
        url=match["url"],
        description=club_name,
        color=discord.Color.green(),
    )
    embed.set_author(name="Registration Now Open")
    embed.add_field(name="Date", value=match["date"] or "TBD", inline=True)
    if match["match_type"]:
        embed.add_field(name="Type", value=match["match_type"], inline=True)
    return embed


def match_cancelled_embed(match, club_name):
    embed = discord.Embed(
        title=match["title"],
        description=club_name,
        color=discord.Color.red(),
    )
    embed.set_author(name="Match Cancelled")
    embed.add_field(name="Date", value=match["date"] or "TBD", inline=True)
    if match["match_type"]:
        embed.add_field(name="Type", value=match["match_type"], inline=True)
    embed.set_footer(text="Cancellation detected automatically — verify with your club directly.")
    return embed


def scrape_failure_embed(failures, consecutive, last_success):
    embed = discord.Embed(
        title="Scraping is failing",
        description=(
            f"The last **{consecutive}** scrape cycles failed for every tracked club. "
            "New matches and registration openings are not being detected."
        ),
        color=discord.Color.red(),
    )
    embed.set_author(name="PractiScore Neo — Alert")
    for name, error in failures[:5]:
        embed.add_field(name=name, value=f"```{error[:300]}```", inline=False)
    embed.add_field(
        name="Last successful scrape",
        value=(
            last_success.strftime("%b %d, %Y at %I:%M %p")
            if last_success
            else "None since the bot last started"
        ),
        inline=False,
    )
    embed.set_footer(text="You'll get one more DM when scraping recovers.")
    return embed


def scrape_recovered_embed(failed_cycles, recovered_at):
    embed = discord.Embed(
        title="Scraping recovered",
        description=f"Scraping is working again after {failed_cycles} failed cycles.",
        color=discord.Color.green(),
    )
    embed.set_author(name="PractiScore Neo — Alert")
    embed.add_field(
        name="Recovered at",
        value=recovered_at.strftime("%b %d, %Y at %I:%M %p"),
        inline=False,
    )
    return embed


def match_view(url, label):
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    return view
