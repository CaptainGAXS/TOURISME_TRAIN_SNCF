"""Build data/station_transfers.csv: time to go from one SNCF station to another one of
the same city by local public transport (metro, tram, bus, airport shuttle...).

The SNCF timetable has no transfers between stations, so without this file the journey
planner sometimes goes through another city to come back (e.g. Mâcon -> Mâcon Loché TGV
via Paris). For each city below, we use the official timetable (GTFS) of its local
network, saved in data/raw/transit/ (download commands in scripts/data_prep/DATA.md).

Method: the same Connection Scan as the journey planner (scripts/itinerary/planner.py),
run on the local network for one weekday, departures every 15 min between 10:00 and
16:00. A time = walk from the SNCF station to a nearby stop, wait, ride (with the
network's own transfer times when it has them), walk to the other SNCF station.
We keep the median over the departures.

Stations used: SNCF stations served by trains, within RADIUS_KM of the city center and
less than ACCESS_METERS from a stop of the local network.

Run from the project root (a few minutes):
    python scripts/data_prep/build_station_transfers.py
"""

import statistics
import sys
import zipfile
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "scripts" / "itinerary"))
from network import DETOUR, WALK_SPEED, distance_m, load_stations, read_gtfs, to_seconds  # noqa: E402
from planner import scan  # noqa: E402

TRANSIT_DIR = ROOT / "data" / "raw" / "transit"
OUT = ROOT / "data" / "station_transfers.csv"

# GTFS route_type: 0 tram, 1 metro, 2 rail, 3 bus, 6 gondola, 7 funicular (None = all)
CITIES = {
    "Paris": {"file": "paris_idfm.zip", "network": "IDFM", "modes": {"0", "1", "2"},
              "center": (48.857, 2.352), "radius_km": 35, "label": "metro/RER"},
    "Lyon": {"file": "lyon_tcl.zip", "network": "TCL", "modes": None,
             "center": (45.760, 4.850), "radius_km": 30, "label": "TCL"},
    "Lille": {"file": "lille_ilevia.zip", "network": "ilevia", "modes": {"0", "1"},
              "center": (50.630, 3.063), "radius_km": 20, "label": "metro/tram"},
    "Toulouse": {"file": "toulouse_tisseo.zip", "network": "Tisseo", "modes": {"0", "1", "6"},
                 "center": (43.604, 1.444), "radius_km": 20, "label": "metro/tram"},
    "Montpellier": {"file": "montpellier_tam.zip", "network": "TaM", "modes": {"0"},
                    "center": (43.611, 3.877), "radius_km": 20, "label": "tram"},
    "Clermont-Ferrand": {"file": "clermont_t2c.zip", "network": "T2C", "modes": None,
                         "center": (45.778, 3.087), "radius_km": 15, "label": "tram/bus"},
    "Macon": {"file": "macon_trema.zip", "network": "TreMA", "modes": None,
              "center": (46.307, 4.828), "radius_km": 15, "label": "bus"},
    "Aix-Marseille": {"file": "aix_marseille.zip", "network": "Aix-Marseille-Provence",
                      "modes": None, "center": (43.400, 5.400), "radius_km": 35,
                      "label": "local transit"},
}

STARTS = range(10 * 3600, 16 * 3600 + 1, 15 * 60)  # departures every 15 min, 10:00-16:00
WINDOW = 2 * 3600  # only look at connections in the 2 h after departure
ACCESS_METERS = 500  # stops this close to the SNCF station are used
ACCESS_EXTRA = 3 * 60  # from the train platform to the station exit
MAX_MINUTES = 90  # pairs slower than this are not kept
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class Feed:
    """One GTFS zip of data/raw/transit/."""

    def __init__(self, filename):
        self.path = TRANSIT_DIR / filename
        with zipfile.ZipFile(self.path) as z:
            self.names = set(z.namelist())

    def read(self, name, **options):
        with zipfile.ZipFile(self.path) as z:
            return pd.read_csv(z.open(name), dtype=str, **options)

    def services_by_date(self):
        """{date: set of service_ids} from calendar.txt and/or calendar_dates.txt."""
        by_date = {}
        if "calendar.txt" in self.names:
            for row in self.read("calendar.txt").itertuples():
                for day in pd.date_range(row.start_date, row.end_date):
                    if getattr(row, WEEKDAYS[day.weekday()]) == "1":
                        by_date.setdefault(day.strftime("%Y%m%d"), set()).add(row.service_id)
        if "calendar_dates.txt" in self.names:
            for row in self.read("calendar_dates.txt").itertuples():
                services = by_date.setdefault(row.date, set())
                if row.exception_type == "1":
                    services.add(row.service_id)
                else:
                    services.discard(row.service_id)
        return by_date


def pick_date(feed):
    """A normal weekday: the upcoming Tuesday (from today) with the most services running."""
    by_date = feed.services_by_date()
    tuesdays = [d for d in by_date if pd.Timestamp(d).weekday() == 1]
    today = pd.Timestamp.today().strftime("%Y%m%d")
    upcoming = [d for d in tuesdays if d >= today] or tuesdays  # old feed: use any Tuesday
    date = max(upcoming, key=lambda d: len(by_date[d]))
    return date, by_date[date]


def load_connections(feed, modes, services):
    """Connections of that day (same format as network.py) sorted by departure, and the
    set of stops they use."""
    routes = feed.read("routes.txt")
    if modes is not None:
        routes = routes[routes["route_type"].isin(modes)]
    trips = feed.read("trips.txt", usecols=["route_id", "service_id", "trip_id"])
    trip_ids = set(trips[trips["route_id"].isin(set(routes["route_id"]))
                         & trips["service_id"].isin(services)]["trip_id"])

    columns = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]
    optional = [c for c in ("pickup_type", "drop_off_type")
                if c in feed.read("stop_times.txt", nrows=0).columns]
    parts = []
    with zipfile.ZipFile(feed.path) as z:  # stop_times.txt can be big: read it in chunks
        for chunk in pd.read_csv(z.open("stop_times.txt"), dtype=str,
                                 usecols=columns + optional, chunksize=1_000_000):
            parts.append(chunk[chunk["trip_id"].isin(trip_ids)])
    st = pd.concat(parts).dropna(subset=["arrival_time", "departure_time"])
    for c in ("pickup_type", "drop_off_type"):
        if c not in st:
            st[c] = "0"
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    st = st.sort_values(["trip_id", "stop_sequence"])
    st["dep"] = st["departure_time"].map(to_seconds)
    st["arr"] = st["arrival_time"].map(to_seconds)

    nxt = st.shift(-1)  # two consecutive stops of the same trip = one connection
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
    connections = connections[(connections["dep"] >= STARTS[0])
                              & (connections["dep"] <= STARTS[-1] + WINDOW)].sort_values("dep")
    return connections.to_dict("records"), set(st["stop_id"])


def load_footpaths(feed, stops):
    """Walking between stops: the network's transfers.txt when it has one, plus stops
    less than 200 m apart (needed when transfers.txt is missing)."""
    footpaths = {}

    def add(a, b, seconds):
        footpaths.setdefault(a, []).append((b, seconds, "walk"))

    if "transfers.txt" in feed.names:
        transfers = feed.read("transfers.txt")
        if "min_transfer_time" in transfers:
            transfers = transfers[transfers["from_stop_id"].isin(stops.index)
                                  & transfers["to_stop_id"].isin(stops.index)]
            for a, b, t in zip(transfers["from_stop_id"], transfers["to_stop_id"],
                               transfers["min_transfer_time"].fillna("120")):
                if a != b:
                    add(a, b, int(float(t)))

    lat, lon = stops["lat"].to_numpy(), stops["lon"].to_numpy()
    for i, a in enumerate(stops.index):
        x = np.radians(lon - lon[i]) * np.cos(np.radians((lat + lat[i]) / 2))
        d = 6_371_000 * np.hypot(x, np.radians(lat - lat[i]))
        for j in np.nonzero((d <= 200) & (d > 0))[0]:
            add(a, stops.index[j], int(d[j] * DETOUR / WALK_SPEED) + 60)
    return footpaths


def train_stations():
    """SNCF stations served by at least one train (not only by SNCF buses)."""
    sncf, platform_to_station = load_stations()
    platforms = read_gtfs("stop_times.txt")["stop_id"].drop_duplicates()
    is_bus = platforms.str.contains(r"OCE(?:Car |Navette)", regex=True)
    served = {platform_to_station[p] for p in platforms[~is_bus]}
    return {sid: s for sid, s in sncf.items() if sid in served}


def access_stops(sncf, stops, city):
    """{sncf station id: [(stop_id, walking seconds)]} for the stations of this city."""
    lat, lon = stops["lat"].to_numpy(), stops["lon"].to_numpy()
    access = {}
    for sid, s in sncf.items():
        if distance_m(*city["center"], s["lat"], s["lon"]) > city["radius_km"] * 1000:
            continue
        x = np.radians(lon - s["lon"]) * np.cos(np.radians((lat + s["lat"]) / 2))
        d = 6_371_000 * np.hypot(x, np.radians(lat - s["lat"]))
        near = np.nonzero(d <= ACCESS_METERS)[0]
        if len(near):
            access[sid] = [(stops.index[j], int(d[j] * DETOUR / WALK_SPEED) + ACCESS_EXTRA)
                           for j in near]
    return access


def build_city(name, city, sncf):
    feed = Feed(city["file"])
    date, services = pick_date(feed)
    connections, used = load_connections(feed, city["modes"], services)
    departures = [c["dep"] for c in connections]
    stops = feed.read("stops.txt")
    stops = stops[stops["stop_id"].isin(used)].set_index("stop_id")
    stops["lat"], stops["lon"] = stops["stop_lat"].astype(float), stops["stop_lon"].astype(float)
    footpaths = load_footpaths(feed, stops)
    access = access_stops(sncf, stops, city)
    print(f"{name}: {date}, {len(connections)} connections, {len(access)} SNCF stations")

    source = f"{city['network']} GTFS {date}, median of departures 10:00-16:00"
    rows = []
    for a in access:
        paths = dict(footpaths)
        paths["ORIGIN"] = [(stop, seconds, "walk") for stop, seconds in access[a]]
        times = {b: [] for b in access if b != a}
        for t in STARTS:
            window = connections[bisect_left(departures, t):bisect_right(departures, t + WINDOW)]
            arrival, _ = scan(window, paths, "ORIGIN", t, transfer_seconds=0)
            for b in times:
                reached = [arrival[stop] + s for stop, s in access[b] if stop in arrival]
                if reached:
                    times[b].append(min(reached) - t)
        for b, values in times.items():
            if len(values) >= len(STARTS) / 2:  # reachable for at least half of the departures
                minutes = round(statistics.median(values) / 60)
                if minutes <= MAX_MINUTES:
                    rows.append({"from_uic": a.removeprefix("StopArea:OCE"),
                                 "to_uic": b.removeprefix("StopArea:OCE"),
                                 "minutes": minutes, "mode": city["label"], "source": source})
    return rows


def main():
    sncf = train_stations()
    rows = []
    for name, city in CITIES.items():
        rows += build_city(name, city, sncf)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"Saved {len(rows)} pairs to {OUT}")


if __name__ == "__main__":
    main()
