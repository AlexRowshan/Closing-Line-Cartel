"""
Sport-specific configuration for CBB and NBA analysis modes.
"""

CBB_TEAM_ABBREV = {
    "st": "state",
    "penn st": "penn state",
    "michigan st": "michigan state",
    "ohio st": "ohio state",
    "iowa st": "iowa state",
    "kansas st": "kansas state",
    "utah st": "utah state",
    "colorado st": "colorado state",
    "san jose st": "san jose state",
    "fresno st": "fresno state",
    "boise st": "boise state",
    "oregon st": "oregon state",
    "arizona st": "arizona state",
    "washington st": "washington state",
    "florida st": "florida state",
    "nc st": "nc state",
    "n carolina st": "nc state",
    "north carolina st": "nc state",
    "usc": "usc",
    "ucf": "ucf",
    "vmi": "virginia military",
    "smu": "southern methodist",
    "tcu": "tcu",
    "lsu": "louisiana state",
    "ole miss": "ole miss",
    "unlv": "unlv",
    "utep": "utep",
    "utsa": "utsa",
    "uab": "uab",
    "fiu": "florida international",
    "fau": "florida atlantic",
    "niu": "northern illinois",
    "uic": "illinois chicago",
    "uconn": "connecticut",
    "brigham young": "byu",
}

NBA_TEAM_ABBREV = {
    # Abbreviated city/team names → full team name
    # (word-prefix matching handles "Golden State" → "Golden State Warriors" automatically;
    #  these handle cases where VSIN uses 2-3 letter codes or non-standard shortening)
    "gs": "golden state warriors",
    "gsw": "golden state warriors",
    "okc": "oklahoma city thunder",
    "sa": "san antonio spurs",
    "sas": "san antonio spurs",
    "no": "new orleans pelicans",
    "nop": "new orleans pelicans",
    "ny": "new york knicks",
    "nyk": "new york knicks",
    "la lakers": "los angeles lakers",
    "lal": "los angeles lakers",
    "la clippers": "los angeles clippers",
    "lac": "los angeles clippers",
    "phx": "phoenix suns",
    "phi": "philadelphia 76ers",
    "76ers": "philadelphia 76ers",
    "philly": "philadelphia 76ers",
    "mem": "memphis grizzlies",
    "mil": "milwaukee bucks",
    "min": "minnesota timberwolves",
    "por": "portland trail blazers",
    "utah": "utah jazz",
    "cha": "charlotte hornets",
    "was": "washington wizards",
    "wsh": "washington wizards",
    "bkn": "brooklyn nets",
    "bk": "brooklyn nets",
    "tor": "toronto raptors",
    "orl": "orlando magic",
    "dal": "dallas mavericks",
    "sac": "sacramento kings",
}

SPORT_CONFIGS = {
    "cbb": {
        # CBB VSIN: one base URL, then click DK (default) and Circa tabs
        "vsin_dk_url": "https://data.vsin.com/college-basketball/betting-splits/",
        "vsin_circa_url": None,  # reached via tab click on the same page
        "vsin_use_tabs": True,
        "oddstrader_spreads_url": "https://www.oddstrader.com/ncaa-college-basketball/",
        "oddstrader_totals_url": "https://www.oddstrader.com/ncaa-college-basketball/?eid&g=game&m=total",
        "team_abbrev": CBB_TEAM_ABBREV,
        "display_name": "CBB",
        "threshold": 25,
    },
    "nba": {
        # NBA VSIN: separate direct URLs per book — no tab clicking needed
        "vsin_dk_url": "https://data.vsin.com/betting-splits/?bookid=dk&view=nba",
        "vsin_circa_url": "https://data.vsin.com/betting-splits/?bookid=circa&view=nba",
        "vsin_use_tabs": False,
        "oddstrader_spreads_url": "https://www.oddstrader.com/nba/",
        "oddstrader_totals_url": "https://www.oddstrader.com/nba/?eid&g=game&m=total",
        "team_abbrev": NBA_TEAM_ABBREV,
        "display_name": "NBA",
        "threshold": 20,
    },
}


def get_config(sport: str) -> dict:
    """Return the config dict for the given sport ('cbb' or 'nba')."""
    return SPORT_CONFIGS.get(sport.lower(), SPORT_CONFIGS["cbb"])
