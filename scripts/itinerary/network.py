"""
Load the SNCF GTFS timetable for one day and turn it into a simple network

Data: data/gtfs_sncf.zip, read directly from the zip (no need to unzip).
    To update it (feed valid until 2027-04-30), download:
    https://www.data.gouv.fr/api/1/datasets/r/9ae758ec-cd7a-40cd-a890-bb3963224942

Output:
    stations    {station_id: {"name", "lat", "lon"}}
    connections list of {"trip", "from", "to", "dep", "arr", ...} sorted by departure time.
                One connection = a train going from one stop to the next one
    trips       {trip_id: {"kind", "number", "stops": [station_id, ...]}}
    footpaths   {station_id: [(other_station_id, seconds, mode), ...]}
                mode "walk": stations closer than MAX_WALK_METERS
                other modes ("metro/RER", "tram", "bus"...): local public transport between
                SNCF stations of the same city, from data/station_transfers.csv
                (built by scripts/data_prep/build_station_transfers.py)
"""

import math
import zipfile
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
GTFS_ZIP = ROOT / "data" / "gtfs_sncf.zip"
STATION_TRANSFERS_CSV = ROOT / "data" / "station_transfers.csv"

MAX_WALK_METERS = 1000  # walk between two stations if they are closer than this
WALK_SPEED = 4.5 / 3.6  # m/s (4.5 km/h)
DETOUR = 1.3  # streets are not straight lines -> for making it simple. just multiply the distance by this factor to get a more realistic walking time


def to_seconds(time_text):
    """'07:16:00' -> 26160. Note: GTFS allows times > 24h, e.g. '25:16:00'."""
    h, m, s = time_text.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def read_gtfs(name):
    """Read one file of the GTFS (e.g. 'stops.txt') directly from the zip."""
    with zipfile.ZipFile(GTFS_ZIP) as z:
        return pd.read_csv(z.open(name), dtype=str)


def uic_to_station_id(uic_text, stations):
    """UIC code(s) from data/stations.csv -> GTFS station_id, or None if not in the GTFS.
    '87547026;87547000' -> 'StopArea:OCE87547000' (first code found in the GTFS)."""
    for code in str(uic_text).split(";"):
        station_id = "StopArea:OCE" + code.strip()
        if station_id in stations:
            return station_id
    return None


def distance_m(lat1, lon1, lat2, lon2):
    """Approximate distance in meters"""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6_371_000 * math.hypot(x, y)


# stations, platforms -> stations
def load_stations():
    stops = read_gtfs("stops.txt")

    # location_type 1 = station (StopArea), the others are platforms (StopPoint)
    areas = stops[stops["location_type"] == "1"]
    stations = {
        row.stop_id: {
            "name": row.stop_name,
            "lat": float(row.stop_lat),
            "lon": float(row.stop_lon),
        }
        for row in areas.itertuples()
    }

    points = stops[stops["location_type"] != "1"]
    platform_to_station = dict(zip(points["stop_id"], points["parent_station"]))
    return stations, platform_to_station


# Output: dict of station_id -> list of (other_station_id, seconds, mode)
def build_footpaths(stations):
    """For each station, the stations reachable on foot and how long it takes."""
    footpaths = {s: [] for s in stations}
    # sorted from south to north, so we can stop looking once we are too far north
    items = sorted(stations.items(), key=lambda item: item[1]["lat"])
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1 :]:
            if sb["lat"] - sa["lat"] > 0.01:  # 0.01° of latitude ≈ 1.1 km
                break
            d = distance_m(sa["lat"], sa["lon"], sb["lat"], sb["lon"])
            if d <= MAX_WALK_METERS:
                seconds = int(d * DETOUR / WALK_SPEED)
                footpaths[a].append((b, seconds, "walk"))
                footpaths[b].append((a, seconds, "walk"))

    # local public transport between SNCF stations of the same city (one row per direction)
    if not STATION_TRANSFERS_CSV.exists():  # not built yet (build_all_data.py --skip-transfers)
        print(f"[warn] {STATION_TRANSFERS_CSV.name} not found: walking only between stations")
        return footpaths
    transfers = pd.read_csv(STATION_TRANSFERS_CSV, dtype={"from_uic": str, "to_uic": str})
    for row in transfers.itertuples():
        a, b = "StopArea:OCE" + row.from_uic, "StopArea:OCE" + row.to_uic
        if a in stations and b in stations:
            footpaths[a].append((b, row.minutes * 60, row.mode))
    return footpaths


@lru_cache(maxsize=14)
def load_network(date):
    """date: 'YYYYMMDD'. Returns stations, connections, trips, footpaths for that day."""
    stations, platform_to_station = load_stations()

    # 1: Which services run on that day "date"
    calendar = read_gtfs("calendar_dates.txt")
    running = calendar[(calendar["date"] == date) & (calendar["exception_type"] == "1")]
    services = set(running["service_id"])

    # 2: Which trips (= one train run) use those services
    trips_df = read_gtfs("trips.txt")
    trips_df = trips_df[trips_df["service_id"].isin(services)]
    train_number = dict(zip(trips_df["trip_id"], trips_df["trip_headsign"]))

    # 3: Stop times of those trips, in order
    st = read_gtfs("stop_times.txt")
    st = st[st["trip_id"].isin(train_number)]
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    st = st.sort_values(["trip_id", "stop_sequence"])

    # 4: Two consecutive stops of the same trip = one connection
    connections = []
    trips = {}
    for trip_id, stops in st.groupby("trip_id", sort=False):
        rows = stops.to_dict("records")
        # stop_id looks like "StopPoint:OCETGV INOUI-87141002" -> kind "TGV INOUI"
        kind = rows[0]["stop_id"].removeprefix("StopPoint:OCE").rsplit("-", 1)[0]
        trips[trip_id] = {
            "kind": kind,
            "number": train_number[trip_id],
            "stops": [platform_to_station[r["stop_id"]] for r in rows],
        }
        for here, nxt in zip(rows, rows[1:]):
            connections.append(
                {
                    "trip": trip_id,
                    "from": platform_to_station[here["stop_id"]],
                    "to": platform_to_station[nxt["stop_id"]],
                    "dep": to_seconds(here["departure_time"]),
                    "arr": to_seconds(nxt["arrival_time"]),
                    "can_board": here["pickup_type"] != "1",  # 1 = no boarding here
                    "can_alight": nxt["drop_off_type"]
                    != "1",  # 1 = no getting off here
                }
            )

    connections.sort(key=lambda c: c["dep"])
    footpaths = build_footpaths(stations)
    return stations, connections, trips, footpaths
