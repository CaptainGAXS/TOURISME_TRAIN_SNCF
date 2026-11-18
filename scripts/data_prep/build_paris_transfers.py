"""Build data/paris_transfers.csv: time to go from one SNCF station of the Paris area
to another by metro / RER / tram (the SNCF timetable has no transfers between them).

Source: Ile-de-France Mobilites timetable (GTFS), saved as data/raw/idfm_gtfs.zip
    curl -L -o data/raw/idfm_gtfs.zip "https://www.data.gouv.fr/api/1/datasets/r/413988ed-d340-467b-8be2-7b999fcd207a"

Method: the same Connection Scan as the journey planner (scripts/itinerary/planner.py),
run on the metro / RER / tram timetable of one weekday, for departures every 15 min
between 10:00 and 16:00. A time = walk from the SNCF station to a metro/RER/tram stop,
wait, ride (with the official IDFM transfer times when changing lines), walk to the
other SNCF station. We keep the median over the departures.

Run from the project root (about 2 minutes):
    python scripts/data_prep/build_paris_transfers.py
"""

import statistics
import sys
import zipfile
from bisect import bisect_left, bisect_right
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "scripts" / "itinerary"))
from network import DETOUR, WALK_SPEED, distance_m, load_stations, to_seconds  # noqa: E402
from planner import scan  # noqa: E402

IDFM_ZIP = ROOT / "data" / "raw" / "idfm_gtfs.zip"
OUT = ROOT / "data" / "paris_transfers.csv"

DATE = "20261124"  # a Tuesday inside the IDFM feed validity (2026-11-18 -> 2026-12-17)
STARTS = range(10 * 3600, 16 * 3600 + 1, 15 * 60)  # departures every 15 min, 10:00-16:00
WINDOW = 2 * 3600  # only look at metro/RER/tram connections in the 2 h after departure
MODES = {"0", "1", "2"}  # GTFS route_type: tram, metro, rail (RER / Transilien)
ACCESS_METERS = 500  # metro/RER/tram stops this close to the SNCF station are used
ACCESS_EXTRA = 3 * 60  # from the SNCF train platform to the station exit / metro entrance
MAX_MINUTES = 120  # pairs slower than this are not kept
SOURCE = f"IDFM GTFS {DATE}, metro/RER/tram, median of departures 10:00-16:00"

SNCF_STATIONS = {  # UIC code in the SNCF timetable: name
    "87113001": "Paris Est",
    "87271007": "Paris Gare du Nord",
    "87384008": "Paris Saint-Lazare",
    "87391003": "Paris Montparnasse Hall 1 - 2",
    "87391102": "Paris Montparnasse Vaugirard",
    "87547000": "Paris Austerlitz",
    "87686006": "Paris Gare de Lyon Hall 1 - 2",
    "87686667": "Paris Bercy",
    "87271494": "Aeroport Charles de Gaulle 2 TGV",
    "87111849": "Marne-la-Vallee Chessy",
    "87393702": "Massy TGV",
}


def read(name, **options):
    """Read one file of the IDFM GTFS directly from the zip."""
    with zipfile.ZipFile(IDFM_ZIP) as z:
        return pd.read_csv(z.open(name), dtype=str, **options)


def running_services(date):
    """service_ids running on that date (calendar.txt + exceptions in calendar_dates.txt)."""
    weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
        pd.Timestamp(date).weekday()
    ]
    calendar = read("calendar.txt")
    services = set(
        calendar[
            (calendar[weekday] == "1")
            & (calendar["start_date"] <= date)
            & (calendar["end_date"] >= date)
        ]["service_id"]
    )
    exceptions = read("calendar_dates.txt")
    exceptions = exceptions[exceptions["date"] == date]
    services |= set(exceptions[exceptions["exception_type"] == "1"]["service_id"])
    services -= set(exceptions[exceptions["exception_type"] == "2"]["service_id"])
    return services


def load_connections(date):
    """Metro/RER/tram connections of that day (same format as network.py), sorted by
    departure, and the set of stops they use."""
    routes = read("routes.txt")
    rail_routes = set(routes[routes["route_type"].isin(MODES)]["route_id"])
    trips = read("trips.txt", usecols=["route_id", "service_id", "trip_id"])
    trip_ids = set(
        trips[trips["route_id"].isin(rail_routes) & trips["service_id"].isin(running_services(date))][
            "trip_id"
        ]
    )

    # stop_times.txt is big (~680 MB): read it in chunks and keep only those trips
    columns = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
               "pickup_type", "drop_off_type"]
    parts = []
    with zipfile.ZipFile(IDFM_ZIP) as z:
        for chunk in pd.read_csv(z.open("stop_times.txt"), dtype=str, usecols=columns,
                                 chunksize=1_000_000):
            parts.append(chunk[chunk["trip_id"].isin(trip_ids)])
    st = pd.concat(parts).dropna(subset=["arrival_time", "departure_time"])
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    st = st.sort_values(["trip_id", "stop_sequence"])
    st["dep"] = st["departure_time"].map(to_seconds)
    st["arr"] = st["arrival_time"].map(to_seconds)

    # two consecutive stops of the same trip = one connection
    nxt = st.shift(-1)
    same = st["trip_id"] == nxt["trip_id"]
    connections = pd.DataFrame({
        "trip": st["trip_id"][same],
        "from": st["stop_id"][same],
        "to": nxt["stop_id"][same],
        "dep": st["dep"][same],
        "arr": nxt["arr"][same].astype(int),
        "can_board": st["pickup_type"][same].fillna("0") != "1",
        "can_alight": nxt["drop_off_type"][same].fillna("0") != "1",
    })
    connections = connections[
        (connections["dep"] >= STARTS[0]) & (connections["dep"] <= STARTS[-1] + WINDOW)
    ].sort_values("dep")
    return connections.to_dict("records"), set(st["stop_id"])


def load_footpaths(stops_used):
    """Official IDFM walking transfers between stops: {stop: [(other_stop, seconds, 'walk')]}"""
    transfers = read("transfers.txt")
    transfers = transfers[
        transfers["from_stop_id"].isin(stops_used) & transfers["to_stop_id"].isin(stops_used)
    ]
    footpaths = {}
    for a, b, seconds in zip(transfers["from_stop_id"], transfers["to_stop_id"],
                             transfers["min_transfer_time"]):
        footpaths.setdefault(a, []).append((b, int(float(seconds)), "walk"))
    return footpaths


def access_stops(stops_used):
    """{uic: [(idfm_stop, walking seconds)]}: metro/RER/tram stops near each SNCF station."""
    sncf, _ = load_stations()
    idfm = read("stops.txt")
    idfm = idfm[idfm["stop_id"].isin(stops_used)]
    access = {}
    for uic in SNCF_STATIONS:
        s = sncf["StopArea:OCE" + uic]
        access[uic] = []
        for stop_id, lat, lon in zip(idfm["stop_id"], idfm["stop_lat"], idfm["stop_lon"]):
            d = distance_m(s["lat"], s["lon"], float(lat), float(lon))
            if d <= ACCESS_METERS:
                access[uic].append((stop_id, int(d * DETOUR / WALK_SPEED) + ACCESS_EXTRA))
    return access


def main():
    print("Loading the IDFM timetable...")
    connections, stops_used = load_connections(DATE)
    departures = [c["dep"] for c in connections]
    footpaths = load_footpaths(stops_used)
    access = access_stops(stops_used)
    print(f"{len(connections)} connections, {len(stops_used)} stops")

    rows = []
    for a, a_name in SNCF_STATIONS.items():
        print(f"  from {a_name} ({len(access[a])} metro/RER/tram stops nearby)")
        # a virtual "ORIGIN" node: walk from the SNCF station to the nearby stops
        paths = dict(footpaths)
        paths["ORIGIN"] = [(stop, seconds, "walk") for stop, seconds in access[a]]
        times = {b: [] for b in SNCF_STATIONS if b != a}
        for t in STARTS:
            window = connections[bisect_left(departures, t):bisect_right(departures, t + WINDOW)]
            arrival, _ = scan(window, paths, "ORIGIN", t, transfer_seconds=0)
            for b in times:
                reached = [arrival[stop] + seconds for stop, seconds in access[b] if stop in arrival]
                if reached:
                    times[b].append(min(reached) - t)
        for b, values in times.items():
            if len(values) >= len(STARTS) / 2:  # reachable for at least half of the departures
                minutes = round(statistics.median(values) / 60)
                if minutes <= MAX_MINUTES:
                    rows.append({"from_uic": a, "to_uic": b, "minutes": minutes, "source": SOURCE})

    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"Saved {len(rows)} pairs to {OUT}")


if __name__ == "__main__":
    main()
