"""Station-to-station journey planner on the SNCF GTFS feed (no API token needed).

Uses the Connection Scan Algorithm (earliest arrival) at station (StopArea) level,
with a minimum transfer time when changing trains inside a station.

Data (download + unzip into data/raw/gtfs_sncf/):
    https://www.data.gouv.fr/api/1/datasets/r/9ae758ec-cd7a-40cd-a890-bb3963224942

Usage (from the repo root):
    venv/Scripts/python.exe scripts/itinerary/gtfs_journey.py "Nancy" "Strasbourg" --date 20261120 --time 08:00
    venv/Scripts/python.exe scripts/itinerary/gtfs_journey.py 87141002 87212027 -n 5

Stations can be given as a name (looked up in data/raw/gares.csv, then in GTFS
stops.txt) or as an 8-digit UIC code.

Limitations: no walking transfers between different stations (e.g. Paris Est <->
Paris Nord), a single fixed transfer time, and earliest-arrival only (repeated to
list several departures).
"""

import argparse
import csv
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
GTFS_DIR = ROOT / "data" / "raw" / "gtfs_sncf"
GARES_CSV = ROOT / "data" / "raw" / "gares.csv"

INF = 10**9


# ---------------------------------------------------------------- loading


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("-", " ").replace("'", " ").split())


def _to_seconds(col: pd.Series) -> pd.Series:
    parts = col.str.split(":", expand=True).astype(int)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def load_stops() -> tuple[dict, dict, dict]:
    """Returns (stop_point -> station, station -> name, station -> uic)."""
    stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype=str)
    areas = stops[stops["location_type"] == "1"]
    names = dict(zip(areas["stop_id"], areas["stop_name"]))
    uic = {sid: sid.removeprefix("StopArea:OCE") for sid in areas["stop_id"]}
    points = stops[stops["location_type"] != "1"]
    parent = dict(zip(points["stop_id"], points["parent_station"].fillna(points["stop_id"])))
    return parent, names, uic


def active_services(day: datetime) -> set[str]:
    cal = pd.read_csv(GTFS_DIR / "calendar_dates.txt", dtype=str)
    d = day.strftime("%Y%m%d")
    on = cal[(cal["date"] == d) & (cal["exception_type"] == "1")]["service_id"]
    off = cal[(cal["date"] == d) & (cal["exception_type"] == "2")]["service_id"]
    return set(on) - set(off)


@dataclass
class Network:
    # connections sorted by departure time, as parallel lists (fast in pure Python)
    dep_stop: list
    arr_stop: list
    dep_time: list
    arr_time: list
    trip: list
    can_board: list
    can_alight: list
    trip_info: dict  # trip_id -> (mode/route short name, train number, route long name)
    names: dict
    uic: dict


def build_network(day: datetime) -> Network:
    parent, names, uic = load_stops()
    trips = pd.read_csv(GTFS_DIR / "trips.txt", dtype=str)
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype=str)
    trips = trips.merge(routes[["route_id", "route_short_name", "route_long_name", "route_type"]],
                        on="route_id", how="left")

    # trips running today, plus yesterday's trips that run past midnight (times >= 24:00)
    today = active_services(day)
    yesterday = active_services(day - timedelta(days=1))
    trip_today = set(trips.loc[trips["service_id"].isin(today), "trip_id"])
    trip_yday = set(trips.loc[trips["service_id"].isin(yesterday), "trip_id"])

    st = pd.read_csv(GTFS_DIR / "stop_times.txt", dtype=str,
                     usecols=["trip_id", "arrival_time", "departure_time", "stop_id",
                              "stop_sequence", "pickup_type", "drop_off_type"])
    st = st[st["trip_id"].isin(trip_today | trip_yday)].copy()
    st["arr"] = _to_seconds(st["arrival_time"])
    st["dep"] = _to_seconds(st["departure_time"])
    st["seq"] = st["stop_sequence"].astype(int)
    st["station"] = st["stop_id"].map(parent).fillna(st["stop_id"])
    # stop_id looks like "StopPoint:OCETGV INOUI-87141002" -> train category "TGV INOUI"
    st["kind"] = st["stop_id"].str.extract(r"^StopPoint:OCE(.+)-\d+$", expand=False).fillna("?")
    st["board"] = st["pickup_type"].fillna("0") != "1"
    st["alight"] = st["drop_off_type"].fillna("0") != "1"
    st = st.sort_values(["trip_id", "seq"])

    # consecutive stops of the same trip -> one connection
    nxt = st.shift(-1)
    same = st["trip_id"] == nxt["trip_id"]
    conn = pd.DataFrame({
        "trip": st["trip_id"][same],
        "kind": st["kind"][same],
        "dep_stop": st["station"][same],
        "arr_stop": nxt["station"][same],
        "dep_time": st["dep"][same],
        "arr_time": nxt["arr"][same].astype(int),
        "can_board": st["board"][same],
        "can_alight": nxt["alight"][same].astype(bool),
    })

    parts = []
    if trip_today:
        parts.append(conn[conn["trip"].isin(trip_today)])
    if trip_yday:
        y = conn[conn["trip"].isin(trip_yday)].copy()
        y["dep_time"] -= 86400
        y["arr_time"] -= 86400
        y["trip"] = y["trip"] + "@yday"
        parts.append(y[y["dep_time"] >= 0])
    conn = pd.concat(parts).sort_values(["dep_time", "arr_time"], kind="stable")

    kind = conn.drop_duplicates("trip").set_index("trip")["kind"]
    tinfo = trips.set_index("trip_id")[["trip_headsign", "route_long_name"]]
    trip_info = {}
    for t in kind.index:
        base = t.removesuffix("@yday")
        r = tinfo.loc[base] if base in tinfo.index else None
        trip_info[t] = (kind[t],
                        "" if r is None else r["trip_headsign"],
                        "" if r is None or pd.isna(r["route_long_name"]) else r["route_long_name"])

    return Network(
        dep_stop=conn["dep_stop"].tolist(), arr_stop=conn["arr_stop"].tolist(),
        dep_time=conn["dep_time"].tolist(), arr_time=conn["arr_time"].tolist(),
        trip=conn["trip"].tolist(), can_board=conn["can_board"].tolist(),
        can_alight=conn["can_alight"].tolist(), trip_info=trip_info, names=names, uic=uic,
    )


# ---------------------------------------------------------------- station lookup


def resolve_station(query: str, net: Network) -> str:
    """Returns a GTFS StopArea id for a UIC code or a station name."""
    by_uic = {u: sid for sid, u in net.uic.items()}
    if query.isdigit():
        if query in by_uic:
            return by_uic[query]
        sys.exit(f"UIC {query} not found in GTFS")

    q = _norm(query)
    # 1) gares.csv (proper names) -> UIC -> GTFS
    with open(GARES_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    for exact in (True, False):
        for r in rows:
            n = _norm(r["Nom_Gare"])
            if (n == q) if exact else (q in n):
                for code in r["Code_UIC"].split(";"):
                    if code.strip() in by_uic:
                        return by_uic[code.strip()]
    # 2) GTFS stop names
    for exact in (True, False):
        for sid, name in net.names.items():
            n = _norm(name)
            if (n == q) if exact else (q in n):
                return sid
    sys.exit(f"Station not found: {query}")


# ---------------------------------------------------------------- CSA


def earliest_arrival(net: Network, src: str, dst: str, t0: int, transfer: int):
    """Connection Scan Algorithm. Returns a list of legs or None."""
    arrival = {src: t0}
    boarded = {}  # trip -> index of the connection where we boarded
    journey = {}  # station -> (board_conn_idx, alight_conn_idx)

    dep_stop, arr_stop = net.dep_stop, net.arr_stop
    dep_time, arr_time, trip = net.dep_time, net.arr_time, net.trip
    can_board, can_alight = net.can_board, net.can_alight

    # first connection departing at or after t0 (list is sorted by dep_time)
    lo, hi = 0, len(dep_time)
    while lo < hi:
        mid = (lo + hi) // 2
        if dep_time[mid] < t0:
            lo = mid + 1
        else:
            hi = mid
    for i in range(lo, len(dep_time)):
        if dep_time[i] >= arrival.get(dst, INF):
            break
        t = trip[i]
        if t not in boarded:
            s = dep_stop[i]
            if not can_board[i] or s not in arrival:
                continue
            need = arrival[s] + (0 if s == src else transfer)
            if dep_time[i] < need:
                continue
            boarded[t] = i
        a = arr_stop[i]
        if can_alight[i] and arr_time[i] < arrival.get(a, INF):
            arrival[a] = arr_time[i]
            journey[a] = (boarded[t], i)

    if dst not in journey:
        return None
    legs, s = [], dst
    while s != src:
        b, e = journey[s]
        legs.append((b, e))
        s = dep_stop[b]
    return legs[::-1]


def fmt(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


def print_journey(net: Network, legs) -> None:
    first, last = legs[0][0], legs[-1][1]
    dur = net.arr_time[last] - net.dep_time[first]
    print(f"{fmt(net.dep_time[first])} -> {fmt(net.arr_time[last])}  "
          f"({dur // 3600}h{dur % 3600 // 60:02d}, {len(legs) - 1} transfer(s))")
    for b, e in legs:
        mode, number, line = net.trip_info.get(net.trip[b], ("?", "?", ""))
        print(f"    {fmt(net.dep_time[b])} {net.names.get(net.dep_stop[b], net.dep_stop[b])}"
              f"  ->  {fmt(net.arr_time[e])} {net.names.get(net.arr_stop[e], net.arr_stop[e])}"
              f"   [{mode} {number}{' / ' + line if line else ''}]")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("origin")
    p.add_argument("destination")
    p.add_argument("--date", default=(datetime.now() + timedelta(days=1)).strftime("%Y%m%d"),
                   help="YYYYMMDD (default: tomorrow)")
    p.add_argument("--time", default="06:00", help="earliest departure HH:MM (default 06:00)")
    p.add_argument("-n", type=int, default=3, help="number of journeys to list")
    p.add_argument("--transfer", type=int, default=10, help="min transfer time in minutes")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console default (cp932) can't print accents

    day = datetime.strptime(args.date, "%Y%m%d")
    net = build_network(day)
    src, dst = resolve_station(args.origin, net), resolve_station(args.destination, net)
    print(f"{net.names[src]} (UIC {net.uic[src]}) -> {net.names[dst]} (UIC {net.uic[dst]})"
          f"  on {day:%Y-%m-%d}, from {args.time}\n")

    h, m = map(int, args.time.split(":"))
    t, results = h * 3600 + m * 60, []
    while len(results) < args.n:
        legs = earliest_arrival(net, src, dst, t, args.transfer * 60)
        if legs is None:
            break
        arr = net.arr_time[legs[-1][1]]
        # same arrival as previous result but leaving later -> keep only the later departure
        if results and net.arr_time[results[-1][-1][1]] == arr:
            results[-1] = legs
        else:
            results.append(legs)
        t = net.dep_time[legs[0][0]] + 60  # next journey must leave later
    for legs in results:
        print_journey(net, legs)
    if not results:
        print("No journey found.")


if __name__ == "__main__":
    main()
