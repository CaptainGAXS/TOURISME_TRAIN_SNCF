"""
Carbon footprint (kgCO2e per traveller) of the legs of a journey.

Source: SNCF open data "Emissions de CO2e - perimetre complet"
    https://data.sncf.com/explore/dataset/emission-co2-perimetre-complet/
    saved as data/emission_co2_sncf.csv
    (download: https://data.sncf.com/api/explore/v2.1/catalog/datasets/emission-co2-perimetre-complet/exports/csv?delimiter=%2C)

"""

import pandas as pd

from network import ROOT, distance_m
from planner import leg_stations

CO2_CSV = ROOT / "data" / "emission_co2_sncf.csv"

GRAMS_PER_KM = {  # factors found in the SNCF table
    "TGV INOUI": 3.5,
    "OUIGO": 3.5,
    "INTERCITES": 6.7,
    "INTERCITES de nuit": 6.7,
    "Train TER": 23.8,
    "TramTrain": 23.8,
    "Car TER": 38.0,
    "Car à réservation": 38.0,
    "Navette": 38.0,
}
OTHER_GRAMS_PER_KM = 6.8  # ICE, Lyria, ...: median of the international lines

# rail distance from the official table, median
PATH_TO_RAIL = 1.13

CAR_GRAMS_PER_KM = 89.0  # petrol car, 2.2 people (same table)
# road distance / straight line between the two stations, median over the table
STRAIGHT_TO_ROAD = 1.23


def load_official_km():
    """Two dicts {(uic_a, uic_b): km}, in both directions: rail distance and road distance."""
    df = pd.read_csv(CO2_CSV, dtype=str)
    rail, road = {}, {}
    for row in df.itertuples():
        for pair in [
            (row.origine_uic, row.destination_uic),
            (row.destination_uic, row.origine_uic),
        ]:
            rail[pair] = float(row.distance_entre_les_gares)
            road[pair] = float(row.distance_routiere)
    return rail, road


OFFICIAL_RAIL_KM, OFFICIAL_ROAD_KM = load_official_km()  # small file, loaded once


def uic_pair(station_a, station_b):
    """("StopArea:OCE87141002", "StopArea:OCE87113001") -> ("87141002", "87113001")"""
    return station_a.removeprefix("StopArea:OCE"), station_b.removeprefix(
        "StopArea:OCE"
    )


def leg_km(leg, stations, trips):
    """(distance in km, True if official / False if estimated)."""
    pair = uic_pair(leg["from"], leg["to"])
    if (
        pair in OFFICIAL_RAIL_KM
    ):  # in case the SNCF table has a distance for this leg, use it (more accurate than the straight line)
        return OFFICIAL_RAIL_KM[pair], True

    ids = leg_stations(leg, trips)
    meters = sum(
        distance_m(
            stations[a]["lat"],
            stations[a]["lon"],
            stations[b]["lat"],
            stations[b]["lon"],
        )
        for a, b in zip(ids, ids[1:])
    )
    return meters / 1000 * PATH_TO_RAIL, False


def leg_co2(leg, stations, trips):
    """(kgCO2e, True if the distance is official / False if estimated)."""
    if leg["mode"] == "walk":
        return 0.0, True
    km, exact = leg_km(leg, stations, trips)
    grams_per_km = GRAMS_PER_KM.get(trips[leg["trip"]]["kind"], OTHER_GRAMS_PER_KM)
    return km * grams_per_km / 1000, exact


def journey_co2(legs, stations, trips):
    """Whole journey: (kgCO2e, True if every distance is official)."""
    per_leg = [leg_co2(leg, stations, trips) for leg in legs]
    return sum(kg for kg, _ in per_leg), all(exact for _, exact in per_leg)


def car_co2(origin, destination, stations):
    """Same trip by petrol car: (kgCO2e, True if the road distance is official)."""
    pair = uic_pair(origin, destination)
    if pair in OFFICIAL_ROAD_KM:
        km, exact = OFFICIAL_ROAD_KM[pair], True
    else:
        a, b = stations[origin], stations[destination]
        km, exact = (
            distance_m(a["lat"], a["lon"], b["lat"], b["lon"])
            / 1000
            * STRAIGHT_TO_ROAD,
            False,
        )
    return km * CAR_GRAMS_PER_KM / 1000, exact
