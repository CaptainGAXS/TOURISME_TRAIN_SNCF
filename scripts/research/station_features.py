from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree


# La racine du projet est trois niveaux au-dessus de ce fichier.
ROOT = Path(__file__).resolve().parent.parent.parent

# Chaque fichier correspond à une catégorie de POI.
POI_FILES = {
    "hpoi": ROOT / "data" / "hpoi.csv",
    "npoi": ROOT / "data" / "npoi.csv",
    "epoi": ROOT / "data" / "epoi.csv",
    "attraction": ROOT / "data" / "attractions_france.csv",
}
RADIUSES_KM = (20, 15, 10, 5, 3, 1)
EARTH_RADIUS_KM = 6371.0088
WEBSITE_POI_WEIGHT = 3.0


def load_pois() -> pd.DataFrame:
    """Charge les fichiers de POI préparés et supprime les doublons."""
    frames = []
    for category, path in POI_FILES.items():
        # On conserve uniquement les colonnes utiles aux calculs de distance.
        poi = pd.read_csv(path)
        poi = poi.rename(columns={"Latitude": "lat", "Longitude": "lon"})
        required = {"Nom", "Identifiant", "lat", "lon", "Site internet"}
        missing = required - set(poi.columns)
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        poi = poi[
            ["Nom", "Identifiant", "lat", "lon", "Site internet"]
        ].copy()
        poi["lat"] = pd.to_numeric(poi["lat"], errors="coerce")
        poi["lon"] = pd.to_numeric(poi["lon"], errors="coerce")
        poi = poi.dropna(subset=["lat", "lon"])
        poi["category"] = category
        # Une URL non vide indique que le POI possède une fiche/site accessible.
        poi["has_website"] = (
            poi["Site internet"].astype("string").str.strip().fillna("").ne("")
        )
        frames.append(poi)

    # Les fichiers sont réunis pour pouvoir supprimer les doublons communs.
    pois = pd.concat(frames, ignore_index=True)
    pois["Identifiant"] = pois["Identifiant"].astype("string").str.strip()
    pois["Nom"] = pois["Nom"].astype("string").str.strip()

    # Un identifiant non vide est la meilleure clé de dédoublonnage.
    identifier = pois["Identifiant"].fillna("")
    duplicate_id = identifier.ne("") & identifier.duplicated(keep="first")
    # Si plusieurs catégories reprennent le même identifiant, le site internet
    # doit être conservé dès qu'au moins une des lignes en possède un.
    if identifier.ne("").any():
        website_by_id = pois.groupby(identifier, dropna=False)["has_website"].max()
        pois["has_website"] = identifier.map(website_by_id).fillna(False)

    # Pour les lignes sans identifiant, on utilise le nom et les coordonnées.
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

    # Cet index interne permet de relier les POI aux fichiers d'index spatial.
    pois = pois.reset_index(drop=True)
    pois.insert(0, "poi_index", np.arange(len(pois)))
    return pois


def load_stations() -> pd.DataFrame:
    """Charge les gares en conservant les identifiants comme du texte."""
    return pd.read_csv(
        ROOT / "data" / "stations.csv",
        dtype={"station_id": "string", "departement": "string"},
    )


def _get_station(
    stations: pd.DataFrame,
    station_id: str | None,
    station_name: str | None,
) -> pd.Series:
    """Retourne une gare et vérifie que la recherche est non ambiguë."""
    if (station_id is None) == (station_name is None):
        raise ValueError("Provide exactly one of station_id or station_name")

    if station_id is not None:
        matches = stations[stations["station_id"].eq(station_id)]
    else:
        assert station_name is not None
        matches = stations[stations["name"].eq(station_name)]

    if matches.empty:
        raise ValueError("Station not found")
    if len(matches) > 1:
        raise ValueError("station_name matches several stations; use station_id")
    return matches.iloc[0]


def find_nearby_pois(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    *,
    station_id: str | None = None,
    station_name: str | None = None,
    radius_km: float = 5,
) -> pd.DataFrame:
    """Retourne les POI triés par distance autour d'une gare."""
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")

    station = _get_station(stations, station_id, station_name)
    # BallTree avec la métrique haversine attend des coordonnées en radians.
    station_coordinates = np.radians([[station["lat"], station["lon"]]])
    poi_coordinates = np.radians(pois[["lat", "lon"]].to_numpy())
    tree = BallTree(poi_coordinates, metric="haversine")

    # La requête renvoie uniquement les POI du rayon, déjà triés par distance.
    indices, distances = tree.query_radius(
        station_coordinates,
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
    """Construit les liens gare-POI et la gare la plus proche de chaque POI."""
    if max_radius_km <= 0:
        raise ValueError("max_radius_km must be positive")

    # Deux arbres permettent de répondre aux deux besoins avec le même calcul :
    # les POI proches de chaque gare et la gare la plus proche de chaque POI.
    station_coordinates = np.radians(stations[["lat", "lon"]].to_numpy())
    poi_coordinates = np.radians(pois[["lat", "lon"]].to_numpy())
    station_tree = BallTree(station_coordinates, metric="haversine")
    poi_tree = BallTree(poi_coordinates, metric="haversine")

    poi_indices, distances = poi_tree.query_radius(
        station_coordinates,
        r=max_radius_km / EARTH_RADIUS_KM,
        return_distance=True,
        sort_results=True,
    )

    # query_radius renvoie un tableau de tableaux ; on l'aplatit pour créer
    # une ligne par relation gare-POI.
    link_sizes = np.fromiter((len(indices) for indices in poi_indices), dtype=int)
    station_poi_index = pd.DataFrame(
        {
            "station_id": np.repeat(stations["station_id"].to_numpy(), link_sizes),
            "poi_index": np.concatenate(poi_indices),
            "distance_km": np.concatenate(distances) * EARTH_RADIUS_KM,
            "nom_poi": pois["Nom"].to_numpy()[np.concatenate(poi_indices)],
        }
    )

    # Pour chaque POI, on conserve uniquement la gare la plus proche.
    nearest_distances, nearest_indices = station_tree.query(poi_coordinates, k=1)
    poi_nearest_station = pd.DataFrame(
        {
            "poi_index": pois["poi_index"].to_numpy(),
            "nom_poi": pois["Nom"].to_numpy()[nearest_indices[:, 0]],
            "station_id": stations.iloc[nearest_indices[:, 0]]["station_id"].to_numpy(),
            "distance_km": nearest_distances[:, 0] * EARTH_RADIUS_KM,
        }
    )
    return station_poi_index, poi_nearest_station


def find_nearby_pois_from_index(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    station_poi_index: pd.DataFrame,
    *,
    station_id: str | None = None,
    station_name: str | None = None,
    radius_km: float = 5,
) -> pd.DataFrame:
    """Recherche les POI en filtrant un index spatial déjà calculé."""
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")

    station = _get_station(stations, station_id, station_name)
    station_id = station["station_id"]
    # L'index contient déjà toutes les relations jusqu'à 20 km.
    assert station_id is not None
    links = station_poi_index[
        station_poi_index["station_id"].eq(station_id)
        & station_poi_index["distance_km"].le(radius_km)
    ]
    return (
        links.merge(pois, on="poi_index", how="left")
        .sort_values("distance_km")
        .reset_index(drop=True)
    )


def _query_features(
    tree: BallTree,
    coordinates: np.ndarray,
    prefix: str,
    radiuses_km: tuple[int, ...],
    poi_weights: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Compte les POI dans chaque rayon et trouve le plus proche."""
    features = {}
    for radius_km in radiuses_km:
        # Le rayon est converti en radians pour BallTree.
        matches = tree.query_radius(
            coordinates,
            r=radius_km / EARTH_RADIUS_KM,
            return_distance=False,
        )
        counts = np.fromiter(
            (len(poi_indices) for poi_indices in matches),
            dtype=int,
            count=len(matches),
        )
        features[f"{prefix}_count_{radius_km}km"] = counts

        # Un POI avec site internet reçoit un poids supérieur aux autres.
        if poi_weights is not None:
            weighted_counts = np.array(
                [
                    poi_weights[poi_indices].sum()
                    for poi_indices in matches
                ],
                dtype=float,
            )
            features[f"{prefix}_website_weighted_count_{radius_km}km"] = (
                weighted_counts
            )

    # On ajoute aussi la distance vers le POI le plus proche.
    nearest, _ = tree.query(coordinates, k=1)
    features[f"{prefix}_nearest_km"] = nearest[:, 0] * EARTH_RADIUS_KM
    return features


def compute_station_features(
    stations: pd.DataFrame,
    pois: pd.DataFrame,
    radiuses_km: tuple[int, ...] = RADIUSES_KM,
) -> pd.DataFrame:
    """Calcule les features de distance pour toutes les gares."""
    station_coordinates = np.radians(stations[["lat", "lon"]].to_numpy())
    features = stations.copy()

    # Un arbre est construit pour l'ensemble des POI puis pour chaque catégorie.
    for category in ["all", *pois["category"].unique()]:
        category_pois = pois if category == "all" else pois[pois["category"] == category]
        if category_pois.empty:
            continue
        poi_coordinates = np.radians(category_pois[["lat", "lon"]].to_numpy())
        tree = BallTree(poi_coordinates, metric="haversine")
        # Poids 1 sans site, 3 avec site internet.
        poi_weights = np.where(
            category_pois["has_website"].fillna(False).to_numpy(),
            WEBSITE_POI_WEIGHT,
            1.0,
        )
        prefix = "poi" if category == "all" else category
        for feature_name, values in _query_features(
            tree,
            station_coordinates,
            prefix,
            radiuses_km,
            poi_weights,
        ).items():
            features[feature_name] = values

    return features


def main() -> None:
    """Recalcule et sauvegarde les features gare-POI."""
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
