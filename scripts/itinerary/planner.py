"""
Usage (from the repo root):
   python scripts/itinerary/planner.py "Nancy" "Lyon Part Dieu" --date 20261120 --time 07:00 -n 3
"""

import argparse
import sys
import unicodedata

try:
    from .network import load_network
except ImportError:
    from network import load_network

TRANSFER_SECONDS = 10 * 60  # minimum time to change trains


def simplify(text):
    """'Épinal' -> 'epinal' so that searching ignores accents and case."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.lower().replace("-", " ")


def find_station(
    query, stations
):  # return one first station_id whose name matches the query, or None if not found -> not for frontend
    """Returns the station_id whose name matches best (exact name first, then 'contains')."""
    q = simplify(query)
    for sid, s in stations.items():
        if simplify(s["name"]) == q:  # exact match
            return sid
    for sid, s in stations.items():
        if q in simplify(s["name"]):  # contains match
            return sid
    return None  # not found


def scan(
    connections,
    footpaths,
    origin,
    start_time,
    destination=None,
    transfer_seconds=TRANSFER_SECONDS,
):
    """Connection Scan: earliest arrival time at every station reachable from origin.

    Returns (arrival, came_from). With a destination, stops as soon as nothing can
    arrive there earlier; with destination=None, scans the whole day.
    footpaths: {station: [(other_station, seconds, mode), ...]}, mode = "walk", "metro/RER"...
    """
    arrival = {origin: start_time}  # station -> earliest arrival time
    came_from = {}  # station -> the leg that brought us there the fastest
    boarded_at = {}  # trip -> the connection where we got on that train

    def walk_from(station):
        for other, seconds, mode in footpaths.get(station, []):
            if arrival[station] + seconds < arrival.get(other, float("inf")):
                arrival[other] = arrival[station] + seconds
                came_from[other] = {
                    "mode": mode,
                    "from": station,
                    "to": other,
                    "dep": arrival[station],
                    "arr": arrival[other],
                }

    walk_from(
        origin
    )  # initially set the arrival time for the origin station and walk to nearby stations

    for c in connections:
        if c["dep"] < start_time:
            continue  # skip connections that depart before the start time
        if c["dep"] >= arrival.get(destination, float("inf")):
            break  # nothing departing later can arrive earlier

        if c["trip"] not in boarded_at:
            # can we catch this train here?
            if c["from"] not in arrival or not c["can_board"]:
                continue
            ready = arrival[c["from"]] + (
                0 if c["from"] == origin else transfer_seconds
            )
            if ready > c["dep"]:
                continue  # cannot catch this train
            boarded_at[c["trip"]] = c

        # we are on the train: getting off at c["to"], is it better than before?
        if c["can_alight"] and c["arr"] < arrival.get(c["to"], float("inf")):
            arrival[c["to"]] = c["arr"]
            first = boarded_at[c["trip"]]
            came_from[c["to"]] = {
                "mode": "train",
                "trip": c["trip"],
                "from": first["from"],
                "to": c["to"],
                "dep": first["dep"],
                "arr": c["arr"],
            }
            walk_from(c["to"])

    return arrival, came_from


def earliest_arrival(connections, footpaths, origin, destination, start_time):
    """Returns the journey as a list of legs, or None if no journey is found."""
    _, came_from = scan(connections, footpaths, origin, start_time, destination)
    if destination not in came_from:
        return None

    # walk back from the destination to the origin
    legs = []
    station = destination
    while station != origin:
        leg = came_from[station]
        legs.append(leg)
        station = leg["from"]
    return legs[::-1]


def plan(network, origin, destination, start_time, n=3):
    """Up to n journeys, each one leaving later than the previous one."""
    stations, connections, trips, footpaths = network
    journeys = []
    t = start_time
    while len(journeys) < n:
        legs = earliest_arrival(connections, footpaths, origin, destination, t)
        if legs is None:
            break
        # same arrival time as the previous journey but leaving later -> keep the later one
        if journeys and journeys[-1][-1]["arr"] == legs[-1]["arr"]:
            journeys[-1] = legs
        else:
            journeys.append(legs)
        t = legs[0]["dep"] + 60
    return journeys


def travel_times(network, origin, start_time):
    """{station_id: seconds from start_time until arrival} for every reachable station"""
    stations, connections, trips, footpaths = network
    arrival, _ = scan(connections, footpaths, origin, start_time)
    return {station: t - start_time for station, t in arrival.items()}


def leg_stations(leg, trips):
    """Stations passed by a leg, in order (for walking / metro: just start and end)."""
    if leg["mode"] != "train":
        return [leg["from"], leg["to"]]
    stops = trips[leg["trip"]]["stops"]
    start = stops.index(leg["from"])
    end = stops.index(leg["to"], start + 1)
    return stops[start : end + 1]


### display


def hhmm(seconds):  # seconds -> "HH:MM" string
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def describe(legs, stations, trips):  # legs -> text lines (display)
    """Journey as text lines."""
    duration = legs[-1]["arr"] - legs[0]["dep"]
    changes = max(
        0, sum(leg["mode"] == "train" for leg in legs) - 1
    )  # 0 if walking only
    lines = [
        f"{hhmm(legs[0]['dep'])} -> {hhmm(legs[-1]['arr'])}  "
        f"({duration // 3600}h{duration % 3600 // 60:02d}, {changes} transfer(s))"
    ]
    for leg in legs:
        start, end = stations[leg["from"]]["name"], stations[leg["to"]]["name"]
        if leg["mode"] != "train":  # "walk" or "metro/RER"
            what = f"{leg['mode']} {(leg['arr'] - leg['dep']) // 60} min"
        else:
            what = f"{trips[leg['trip']]['kind']} {trips[leg['trip']]['number']}"
        lines.append(
            f"    {hhmm(leg['dep'])} {start}  ->  {hhmm(leg['arr'])} {end}   [{what}]"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("origin")
    parser.add_argument("destination")
    parser.add_argument("--date", required=True, help="YYYYMMDD")
    parser.add_argument("--time", default="06:00", help="HH:MM, earliest departure")
    parser.add_argument("-n", type=int, default=3, help="number of journeys")
    args = parser.parse_args()
    sys.stdout.reconfigure(
        encoding="utf-8"
    )  # Windows console can't print accents otherwise

    network = load_network(args.date)
    stations, connections, trips, footpaths = network
    origin = find_station(args.origin, stations)
    destination = find_station(args.destination, stations)
    if origin is None or destination is None:
        sys.exit("Station not found")

    h, m = args.time.split(":")
    journeys = plan(network, origin, destination, int(h) * 3600 + int(m) * 60, args.n)
    print(
        f"{stations[origin]['name']} -> {stations[destination]['name']}  on {args.date}\n"
    )
    for legs in journeys:
        print(describe(legs, stations, trips))
    if not journeys:
        print("No journey found.")


if __name__ == "__main__":
    main()
