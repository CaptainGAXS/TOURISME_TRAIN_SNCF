from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree


# Racine du projet (trois niveaux au-dessus de ce script)
ROOT = Path(__file__).resolve().parent.parent.parent

# Fichiers sources des points d'intérêt (POI) par catégorie
POI_FILES = {
    "hpoi": ROOT / "data" / "hpoi.csv",               # Patrimoine / patrimoine
    "npoi": ROOT / "data" / "npoi.csv",               # Nature
    "epoi": ROOT / "data" / "epoi.csv",               # Événements
    "attraction": ROOT / "data" / "attractions_france.csv",  # Attractions
}

# Rayons de recherche autour des gares
RADIUSES_KM = (20, 15, 10, 5, 2)
EARTH_RADIUS_KM = 6371.0088

# Coefficient appliqué aux POI disposant d'un site web (gage de fiabilité/visibilité)
WEBSITE_POI_WEIGHT = 3.0


def load_pois() -> pd.DataFrame:
    """Charge tous les fichiers de POI, nettoie les données et supprime les doublons."""
    frames = []
    required_cols = {"Nom", "Identifiant", "Latitude", "Longitude", "Site internet"}

    for category, path in POI_FILES.items():
        poi = pd.read_csv(path)
        missing = required_cols - set(poi.columns)
        if missing:
            raise ValueError(f"{path} : colonnes manquantes -> {', '.join(sorted(missing))}")

        # Conserve les dates des événements pour permettre un filtrage par date.
        columns = ["Nom", "Identifiant", "Latitude", "Longitude", "Site internet"]
        columns.extend(column for column in ("Date début", "Date fin") if column in poi)
        poi = poi[columns].rename(
            columns={"Latitude": "lat", "Longitude": "lon"}
        )
        poi["lat"] = pd.to_numeric(poi["lat"], errors="coerce")
        poi["lon"] = pd.to_numeric(poi["lon"], errors="coerce")
        poi = poi.dropna(subset=["lat", "lon"]).copy()

        poi["category"] = category
        # Indique si le POI possède une URL renseignée
        poi["has_website"] = (
            poi["Site internet"].astype("string").str.strip().fillna("").ne("")
        )
        frames.append(poi)

    # Fusion de toutes les catégories pour détecter les doublons inter-fichiers
    pois = pd.concat(frames, ignore_index=True)
    pois["Identifiant"] = pois["Identifiant"].astype("string").str.strip().fillna("")
    pois["Nom"] = pois["Nom"].astype("string").str.strip()

    # Si un même identifiant apparaît plusieurs fois, on conserve l'info "site web" si au moins une ligne en a un
    has_id = pois["Identifiant"].ne("")
    if has_id.any():
        website_by_id = pois.groupby("Identifiant")["has_website"].max()
        pois["has_website"] = pois["Identifiant"].map(website_by_id).fillna(False)

    # Dédoublonnage par identifiant (si présent) puis par couple (coordonnées + nom normalisé)
    duplicate_id = has_id & pois["Identifiant"].duplicated(keep="first")
    coord_key = (
        pois["lat"].round(6).astype("string")
        + "|"
        + pois["lon"].round(6).astype("string")
    )
    name_key = pois["Nom"].fillna("").str.lower().str.replace(r"\s+", " ", regex=True)
    duplicate_coord_name = (coord_key + "|" + name_key).duplicated(keep="first")

    pois = pois.loc[~(duplicate_id | duplicate_coord_name)].reset_index(drop=True)
    # Identifiant numérique unique utilisé pour les jointures avec l'index spatial
    pois.insert(0, "poi_index", np.arange(len(pois)))
    return pois


def load_stations() -> pd.DataFrame:
    """Charge la liste des gares en conservant les codes en texte."""
    return pd.read_csv(
        ROOT / "data" / "stations.csv",
        dtype={"station_id": "string", "departement": "string"},
    )


def _get_station(
    stations: pd.DataFrame,
    station_id: str | None = None,
    station_name: str | None = None,
) -> pd.Series:
    """Recherche une gare unique par identifiant ou par nom exact."""
    if (station_id is None) == (station_name is None):
        raise ValueError("Fournir exactement un paramètre : station_id ou station_name.")

    if station_id is not None:
        matches = stations[stations["station_id"].eq(station_id)]
    else:
        assert station_name is not None
        matches = stations[stations["name"].eq(station_name)]

    if matches.empty:
        raise ValueError("Gare introuvable.")
    if len(matches) > 1:
        raise ValueError("Plusieurs gares portent ce nom ; utiliser station_id.")
    return matches.iloc[0]


def find_nearby_pois(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    *,
    station_id: str | None = None,
    station_name: str | None = None,
    radius_km: float = 5,
) -> pd.DataFrame:
    """Calcule à la volée les POI situés autour d'une gare, triés par distance."""
    if radius_km <= 0:
        raise ValueError("radius_km doit être strictement positif.")

    station = _get_station(stations, station_id, station_name)
    # BallTree avec la métrique haversine attend des coordonnées en radians
    station_rad = np.radians([[station["lat"], station["lon"]]])
    pois_rad = np.radians(pois[["lat", "lon"]].to_numpy())

    tree = BallTree(pois_rad, metric="haversine")
    indices, distances = tree.query_radius(
        station_rad,
        r=radius_km / EARTH_RADIUS_KM,
        return_distance=True,
        sort_results=True,
    )

    nearby = pois.iloc[indices[0]].copy()
    nearby.insert(0, "distance_km", distances[0] * EARTH_RADIUS_KM)
    return nearby.reset_index(drop=True)


def build_proximity_indexes(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    max_radius_km: float = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pré-calcule deux tables spatiales :
    1. Tous les couples (gare, POI) distants d'au plus `max_radius_km`.
    2. La gare la plus proche pour chaque POI.
    """
    if max_radius_km <= 0:
        raise ValueError("max_radius_km doit être strictement positif.")

    stations_rad = np.radians(stations[["lat", "lon"]].to_numpy())
    pois_rad = np.radians(pois[["lat", "lon"]].to_numpy())

    station_tree = BallTree(stations_rad, metric="haversine")
    poi_tree = BallTree(pois_rad, metric="haversine")

    # 1. Liens gare -> POI dans le rayon maximal
    poi_indices, distances = poi_tree.query_radius(
        stations_rad,
        r=max_radius_km / EARTH_RADIUS_KM,
        return_distance=True,
        sort_results=True,
    )
    counts_per_station = np.fromiter((len(idx) for idx in poi_indices), dtype=int)
    flat_poi_idx = np.concatenate(poi_indices)

    station_poi_index = pd.DataFrame(
        {
            "station_id": np.repeat(stations["station_id"].to_numpy(), counts_per_station),
            "poi_index": flat_poi_idx,
            "distance_km": np.concatenate(distances) * EARTH_RADIUS_KM,
        }
    )

    # 2. Gare la plus proche pour chaque POI
    nearest_dist, nearest_idx = station_tree.query(pois_rad, k=1)
    poi_nearest_station = pd.DataFrame(
        {
            "poi_index": pois["poi_index"].to_numpy(),
            "nom_poi": pois["Nom"].to_numpy(),
            "station_id": stations.iloc[nearest_idx[:, 0]]["station_id"].to_numpy(),
            "distance_km": nearest_dist[:, 0] * EARTH_RADIUS_KM,
        }
    )
    return station_poi_index, poi_nearest_station


def _compute_category_features(
    tree: BallTree,
    station_rad: np.ndarray,
    prefix: str,
    radiuses_km: tuple[int, ...],
    poi_weights: np.ndarray,
) -> dict[str, np.ndarray]:
    """Calcule pour une catégorie donnée :
    - le nombre brut de POI par rayon,
    - le score pondéré par la présence d'un site web,
    - la distance au POI le plus proche.
    """
    features = {}
    for radius_km in radiuses_km:
        matches = tree.query_radius(
            station_rad,
            r=radius_km / EARTH_RADIUS_KM,
            return_distance=False,
        )
        features[f"{prefix}_count_{radius_km}km"] = np.fromiter(
            (len(idx) for idx in matches), dtype=int, count=len(matches)
        )
        features[f"{prefix}_website_weighted_count_{radius_km}km"] = np.fromiter(
            (poi_weights[idx].sum() for idx in matches), dtype=float, count=len(matches)
        )

    nearest_dist, _ = tree.query(station_rad, k=1)
    features[f"{prefix}_nearest_km"] = nearest_dist[:, 0] * EARTH_RADIUS_KM
    return features


def compute_station_features(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    radiuses_km: tuple[int, ...] = RADIUSES_KM,
) -> pd.DataFrame:
    """Enrichit chaque gare avec les compteurs de POI par rayon et catégorie."""
    station_rad = np.radians(stations[["lat", "lon"]].to_numpy())
    features = stations.copy()

    # Calcul global ("all") puis par catégorie touristique
    for category in ["all", *pois["category"].unique()]:
        subset = pois if category == "all" else pois[pois["category"] == category]
        if subset.empty:
            continue

        poi_rad = np.radians(subset[["lat", "lon"]].to_numpy())
        tree = BallTree(poi_rad, metric="haversine")

        # Poids de 3 si le POI a un site internet, 1 sinon
        weights = np.where(
            subset["has_website"].fillna(False).to_numpy(),
            WEBSITE_POI_WEIGHT,
            1.0,
        )
        prefix = "poi" if category == "all" else category
        col_dict = _compute_category_features(
            tree, station_rad, prefix, radiuses_km, weights
        )
        for col_name, values in col_dict.items():
            features[col_name] = values

    return features


def main() -> None:
    """Génère et sauvegarde les features des gares ainsi que les index spatiaux."""
    stations = load_stations()
    pois = load_pois()

    features = compute_station_features(stations, pois)
    features_path = ROOT / "data" / "station_features.csv"
    features.to_csv(features_path, index=False)

    station_poi_index, poi_nearest_station = build_proximity_indexes(stations, pois)
    station_poi_path = ROOT / "data" / "station_poi_index.csv.gz"
    legacy_station_poi_path = ROOT / "data" / "station_poi_index.csv"
    nearest_station_path = ROOT / "data" / "poi_nearest_station.csv"
    station_poi_index.to_csv(station_poi_path, index=False, compression="gzip")
    legacy_station_poi_path.unlink(missing_ok=True)
    poi_nearest_station.to_csv(nearest_station_path, index=False)

    print(f"POI traités : {len(pois)} | Gares enrichies : {len(features)}")
    print(f"Liens gare-POI enregistrés : {len(station_poi_index)}")


if __name__ == "__main__":
    main()