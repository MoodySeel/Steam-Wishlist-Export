#!/usr/bin/env python3

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from typing import Optional


##
## Helpers
##
def pe(msg: str):
    print(msg, file=sys.stderr, end="")


def progress(msg: str):
    if not args.quiet:
        pe(msg)


def request(url: str) -> urllib.request.Request:
    req = urllib.request.Request(url)
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    )
    return req


def integer(value: str, name: str, max: Optional[int] = None) -> int:
    if value is None:
        return 0
    err = "{} must be an integer".format(name)
    if max:
        err = err + " between 0 and {}, inclusive.".format(max)
    try:
        v = int(value)
        if not max or v <= max:
            return v
    except ValueError:
        pass
    pe(err + "\n")
    sys.exit(1)


##
## Command line arguments
##


parser = argparse.ArgumentParser(
    prog="steam_wishlist.py",
    description="Export your Steam wishlist",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Available wishlist fields, see JSON ouput:
    name, capsule, review_score, review_desc, reviews_total, reviews_percent,
    release_date, release_string, platform_icons, subs, type, screenshots,
    review_css, priority, added, background, rank, tags, is_free_game,
    deck_compat, win, mac, linux, free, prerelease

Additional provided fields for CSV output:
    gameid, link, released

Additional fields when using --prices to get price information:
    initial, final, discount_percent, initial_formatted, final_formatted, currency
    """,
)
parser.add_argument(
    "userid",
    metavar="<userid>",
    help="Steam user id, which is a 17 digit number. See https://help.steampowered.com/en/faqs/view/2816-BE67-5B69-0FEC.",
    nargs="?",
)
parser.add_argument(
    "-c",
    "--cookie",
    metavar="<cookie>",
    help="value of steamLoginSecure browser cookie, required for private wishlist",
)
parser.add_argument(
    "-q", "--quiet", help="don't report progress on stderr", action="store_true"
)

group_output = parser.add_mutually_exclusive_group()
group_output.add_argument(
    "-j", "--json", help="output json (default)", action="store_true"
)
group_output.add_argument("-t", "--csv", help="output CSV", action="store_true")
parser.add_argument("-f", "--fields", help="comma-separated list of fields to include")
parser.add_argument(
    "-s",
    "--separator",
    help="field separator used for CSV output (default tab)",
    default="\t",
)
parser.add_argument(
    "--quote",
    help="CSV quoting style (default: never, meaning: escape delimiters occuring in fields)",
    choices=["never", "minimal", "always"],
    default="never",
)

group_sort = parser.add_argument_group("sorting (CSV)")
group_sort.add_argument("--sort", help="sort by <field>", metavar="<field>")
group_sort.add_argument(
    "--num", "--numeric", help="sort numerically", action="store_true"
)
group_sort.add_argument("--reverse", help="reverse sort", action="store_true")

group_save = parser.add_mutually_exclusive_group()
group_save.add_argument(
    "--save", help="save unprocessed wishlist to <file>", metavar="<file>"
)
group_save.add_argument(
    "--load",
    help="load saved wishlist (with --save) from <file> instead of downloading",
    metavar="<file>",
)

group_filters = parser.add_argument_group("filters")
group_filters.add_argument(
    "-p",
    "--platform",
    help="supported platform (linux, win or mac). Can be repeated for multiple platforms",
    choices=["linux", "win", "mac"],
    action="append",
)
group_filters.add_argument("--free", help="free games only", action="store_true")
group_filters.add_argument("--no-free", help="non-free games only", action="store_true")
group_filters.add_argument("--demo", help="games with demos only", action="store_true")
group_filters.add_argument(
    "--achievements", help="games with achievements only", action="store_true"
)
group_filters.add_argument(
    "--cards", help="games with trading cards only", action="store_true"
)
group_filters.add_argument(
    "--released", help="released games only", action="store_true"
)
group_filters.add_argument(
    "--no-released", help="unreleased games only", action="store_true"
)
group_filters.add_argument(
    "--early", help="early access games only", action="store_true"
)
group_filters.add_argument(
    "--no-early", help="no early access games", action="store_true"
)
group_filters.add_argument(
    "--type",
    help="type of app. Can be repeated for multiple types",
    choices=["game", "dlc", "mod", "demo", "application", "music"],
    action="append",
)
group_filters.add_argument(
    "--tag",
    help="list only games with this tag. Can be repeated for multiple tags. Case-insensitive, spaces and non-alphabetic characters are ignored",
    action="append",
)
group_filters.add_argument(
    "--deck",
    help="list only games with a Steam Deck compatibility rating of <int> or higher (must be an int between 0 and 3, inclusive)",
    metavar="<int>",
)

group_price = parser.add_argument_group("price information")
group_price.add_argument(
    "--prices",
    help="fetch current prices and discounts from the store. <country code> is the 2 letter country code for which the regional prices should be fetched. When using --load, prices are loaded from file unless the file does not contain prices",
    metavar="<country code>",
    dest="cc",
)
group_price.add_argument(
    "--refresh",
    help="when used with --load, fetch up to date prices from the Steam store instead of using prices from the loaded file",
    action="store_true",
)

group_price_filter = parser.add_argument_group("price filters")
group_price_filter.add_argument(
    "--discount",
    help="list games with a discount percentage of <int> or more",
    metavar="<int>",
)
group_price_filter.add_argument(
    "--price",
    help="list games with a price of <int> or less. <int> should be an int, for example $19.99 should be specified as 1999",
    metavar="<int>",
)

args = parser.parse_args()

wanted_discount = wanted_discount = integer(args.discount, "Discount", 100)
wanted_price = wanted_price = integer(args.price, "Price")
wanted_deck_rating = wanted_deck_rating = integer(args.deck, "Steam Deck rating", 3)

##
## Fetch wishlist
##
wishlist: dict[str, dict] = {}

if args.load:
    with open(args.load) as file:
        wishlist = json.load(file)
else:
    if not args.userid:
        pe("Missing <userid> or --load\n\n")
        parser.print_help(file=sys.stderr)
        sys.exit(1)

    url: str = (
        "https://store.steampowered.com/wishlist/profiles/{}/wishlistdata/?p=".format(
            args.userid
        )
    )
    page: int = -1
    while True:

        page = page + 1

        progress("Fetching wishlist page {}\n".format(page + 1))

        req = request(url + str(page))
        if args.cookie:
            req.add_header("Cookie", "steamLoginSecure={}".format(args.cookie))

        try:
            with urllib.request.urlopen(req) as response:
                json_obj = json.loads(response.read())
                if not isinstance(json_obj, dict) or not json_obj:
                    break
                for k, v in json_obj.items():
                    wishlist[k] = v
        except urllib.error.HTTPError as e:
            pe("Could not get wishlist. ")
            if args.cookie:
                pe("Is the provided cookie invalid or expired?\n\n")
            else:
                pe("Is the wishlist private?\n\n")
            raise e


##
## Get price information
##
if args.cc and (
    not args.load or "_price" not in list(wishlist.values())[0] or args.refresh
):
    BATCH_SIZE = 100
    gameids = list(wishlist.keys())
    count = 1
    for i in range(0, len(gameids), BATCH_SIZE):
        progress("Fetching price information, batch {}\n".format(count))
        count = count + 1
        batch = gameids[i : i + BATCH_SIZE]
        url = "https://store.steampowered.com/api/appdetails/?filters=price_overview&cc={}&appids={}".format(
            args.cc, ",".join(batch)
        )
        with urllib.request.urlopen(request(url)) as response:
            json_obj = json.loads(response.read())
            for gameid, obj in json_obj.items():
                wishlist[gameid]["_price"] = "fetched"
                if "data" in obj and "price_overview" in obj["data"]:
                    for key, value in obj["data"]["price_overview"].items():
                        wishlist[gameid][key] = value


if args.save:
    with open(args.save, "w") as file:
        json.dump(wishlist, file)


##
## Filters
##
filtered: dict[str, dict] = {}


def clean_str(s: str) -> str:
    return "".join([c.lower() for c in s if c.isalpha()])


filter_lists: list[set[str]] = []
to_load = []
if args.demo:
    to_load.append("demos")
if args.cards:
    to_load.append("cards")
if args.achievements:
    to_load.append("achievements")
for tl in to_load:
    url = "https://raw.githubusercontent.com/BlueBoxWare/steamdb/main/lists/" + tl
    progress("Loading {}\n".format(tl))
    with urllib.request.urlopen(request(url)) as response:
        filter_lists.append({s.decode("utf-8") for s in response.read().split(b"\n")})

for gameid, fields in wishlist.items():
    add_game = True

    if args.platform:
        add_game = False
        for platform in ["linux", "win", "mac"]:
            if fields.get(platform, None) and platform in args.platform:
                add_game = True

    if args.type:
        add_game = add_game and fields.get("type", "").lower() in args.type

    if args.free and not fields.get("is_free_game", False):
        add_game = False

    if args.no_free and fields.get("is_free_game", False):
        add_game = False

    if args.released and fields.get("prerelease", False):
        add_game = False

    if args.no_released and not fields.get("prerelease", False):
        add_game = False

    if args.early and not fields.get("early_access", False):
        add_game = False

    if args.no_early and fields.get("early_access", False):
        add_game = False

    if add_game and args.tag:
        add_game = False
        tags = [clean_str(tag) for tag in fields["tags"]]
        for wanted_tag in args.tag:
            if clean_str(wanted_tag) in tags:
                add_game = True

    if add_game and args.discount:
        add_game = int(fields.get("discount_percent", 0)) >= wanted_discount

    if add_game and args.price:
        add_game = int(fields.get("final", 0)) <= wanted_price

    if add_game and args.deck:
        add_game = int(fields.get("deck_compat", 0)) >= wanted_deck_rating

    for filter_list in filter_lists:
        add_game = add_game and gameid in filter_list

    if add_game:
        filtered[gameid] = fields

wishlist = filtered

##
## Output
##
wanted_fields: Optional[list[str]] = (
    None if not getattr(args, "fields", None) else args.fields.split(",")
)

if not args.csv:

    output = {}

    for gameid, fields in wishlist.items():
        output_fields = {}
        for field_name, field_value in fields.items():
            if not wanted_fields or field_name in wanted_fields:
                output_fields[field_name] = field_value
        if wanted_fields and "link" in wanted_fields:
            output_fields["link"] = "https://store.steampowered.com/app/{}".format(
                gameid
            )
        output[gameid] = output_fields

    print(json.dumps(output, indent=4, ensure_ascii=False))

else:

    if not wanted_fields:
        wanted_fields = ["id"]

    quoting = csv.QUOTE_NONE
    if args.quote == "minimal":
        quoting = csv.QUOTE_MINIMAL
    elif args.quote == "always":
        quoting = csv.QUOTE_ALL

    writer = csv.writer(
        sys.stdout, delimiter=args.separator, quoting=quoting, escapechar="\\"
    )

    def sorter(item):
        value = item[1].get("added")
        if args.sort:
            if args.sort in ["id", "gameid"]:
                value = item[0]
            else:
                value = item[1].get(args.sort, 0 if args.num else "")
        if args.num or str(value).isdigit():
            return int(value)
        return str(value)

    for gameid, fields in sorted(wishlist.items(), key=sorter, reverse=args.reverse):
        output_fields = []
        for field in wanted_fields:
            if field == "id" or field == "gameid":
                output_fields.append(gameid)
            elif field == "released":
                output_fields.append("" if fields.get("prerelease", False) else "1")
            elif field == "link" or field == "url":
                output_fields.append(
                    "https://store.steampowered.com/app/{}".format(gameid)
                )
            else:
                value = fields.get(field, "")
                if type(value) is list:
                    value = ":".join(value)
                output_fields.append(value)
        writer.writerow(output_fields)
