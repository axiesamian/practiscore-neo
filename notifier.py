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


def match_view(url, label):
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    return view
