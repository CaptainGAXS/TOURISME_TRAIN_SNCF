from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree


ROOT = Path(__file__).resolve().parent
POI_FILES = {
    "hpoi": ROOT / "data" / "hpoi.csv",
    "npoi": ROOT / "data" / "npoi.csv",
    "epoi": ROOT / "data" / "epoi.csv",
    "attraction": ROOT / "data" / "attractions_france.csv",
}
RADIUSES_KM = (20, 15, 10, 5, 3, 1)
EARTH_RADIUS_KM = 6371.0088


def load_pois() -> pd.DataFrame:
    """Load and deduplicate all prepared POI files."""
    frames = []
    for category, path in POI_FILES.items():
        poi = pd.read_csv(path)
        poi = poi.rename(columns={"Latitude": "lat", "Longitude": "lon"})
        required = {"Nom", "Identifiant", "lat", "lon"}
        missing = required - set(poi.columns)
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        poi = poi[["Nom", "Identifiant", "lat", "lon"]].copy()
        poi["lat"] = pd.to_numeric(poi["lat"], errors="coerce")
        poi["lon"] = pd.to_numeric(poi["lon"], errors="coerce")
        poi = poi.dropna(subset=["lat", "lon"])
        poi["category"] = category
        frames.append(poi)

    pois = pd.concat(frames, ignore_index=True)
    pois["Identifiant"] = pois["Identifiant"].astype("string").str.strip()
    pois["Nom"] = pois["Nom"].astype("string").str.strip()

    identifier = pois["Identifiant"].fillna("")
    duplicate_id = identifier.ne("") & identifier.duplicated(keep="first")
    coordinate_key = (
        pois["lat"].round(6).astype("string")
        + "|"
        + pois["lon"].round(6).astype("string")
    )
    name_key = (
        pois["Nom"]
        .fillna("")
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )
    duplicate_name_coordinates = (
        coordinate_key + "|" + name_key
    ).duplicated(keep="first")
    pois = pois.loc[~(duplicate_id | duplicate_name_coordinates)]
    return pois.reset_index(drop=True)


def load_stations() -> pd.DataFrame:
    return pd.read_csv(
        ROOT / "data" / "stations.csv",
        dtype={"station_id": "string", "uic": "string", "insee": "string"},
    )


def find_nearby_pois(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    *,
    station_id: str | None = None,
    station_name: str | None = None,
    radius_km: float = 5,
) -> pd.DataFrame:
    """Return POIs sorted by distance from one station."""
    if (station_id is None) == (station_name is None):
        raise ValueError("Provide exactly one of station_id or station_name")
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")

    if station_id is not None:
        matches = stations[stations["station_id"].eq(station_id)]
    else:
        matches = stations[stations["name"].eq(station_name)]
    if matches.empty:
        raise ValueError("Station not found")
    if len(matches) > 1:
        raise ValueError("station_name matches several stations; use station_id")

    station = matches.iloc[0]
    station_coordinates = np.radians([[station["lat"], station["lon"]]])
    poi_coordinates = np.radians(pois[["lat", "lon"]].to_numpy())
    tree = BallTree(poi_coordinates, metric="haversine")
    indices, distances = tree.query_radius(
        station_coordinates,
        r=radius_km / EARTH_RADIUS_KM,
        return_distance=True,
        sort_results=True,
    )

    nearby = pois.iloc[indices[0]].copy()
    nearby.insert(0, "distance_km", distances[0] * EARTH_RADIUS_KM)
    return nearby.reset_index(drop=True)


def _query_features(
    tree: BallTree,
    coordinates: np.ndarray,
    prefix: str,
    radiuses_km: tuple[int, ...],
) -> dict[str, np.ndarray]:
    features = {}
    for radius_km in radiuses_km:
        counts = tree.query_radius(
            coordinates,
            r=radius_km / EARTH_RADIUS_KM,
            count_only=True,
        )
        features[f"{prefix}_count_{radius_km}km"] = counts

    nearest, _ = tree.query(coordinates, k=1)
    features[f"{prefix}_nearest_km"] = nearest[:, 0] * EARTH_RADIUS_KM
    return features


def compute_station_features(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    radiuses_km: tuple[int, ...] = RADIUSES_KM,
) -> pd.DataFrame:
    """Compute POI counts and nearest distances for every station."""
    station_coordinates = np.radians(stations[["lat", "lon"]].to_numpy())
    features = stations.copy()

    for category in ["all", *pois["category"].unique()]:
        category_pois = pois if category == "all" else pois[pois["category"] == category]
        if category_pois.empty:
            continue
        poi_coordinates = np.radians(category_pois[["lat", "lon"]].to_numpy())
        tree = BallTree(poi_coordinates, metric="haversine")
        prefix = "poi" if category == "all" else category
        for name, values in _query_features(
            tree, station_coordinates, prefix, radiuses_km
        ).items():
            features[name] = values

    return features


def main() -> None:
    stations = load_stations()
    pois = load_pois()
    features = compute_station_features(stations, pois)
    output = ROOT / "data" / "station_features.csv"
    features.to_csv(output, index=False)
    print(f"POIs used: {len(pois)}")
    print(f"Stations enriched: {len(features)}")
    print(f"Saved to {output}")


if __name__ == "__main__":
    main()
