from dataclasses import dataclass
import unicodedata

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.neighbors import BallTree
from sklearn.preprocessing import StandardScaler

from scripts.research.station_features import (
    EARTH_RADIUS_KM,
    RADIUSES_KM,
    ROOT,
    load_pois,
)


# Correspondance entre préférences utilisateur et préfixes des colonnes de POI
CATEGORY_COLUMNS = {
    "culture": "hpoi",
    "nature": "npoi",
    "events": "epoi",
    "attractions": "attraction",
}
POI_CATEGORY_BY_TYPE = {prefix: cat for cat, prefix in CATEGORY_COLUMNS.items()}

# Départements de la région parisienne (Île-de-France)
PARIS_REGION_DEPARTMENTS = frozenset({"75", "77", "78", "91", "92", "93", "94", "95"})



@dataclass(frozen=True)
class RecommendationCriteria:
    """Paramètres de recherche exposés à l'utilisateur."""

    culture: float = 0.25
    nature: float = 0.25
    events: float = 0.25
    attractions: float = 0.25
    radius_km: int = 10
    departure_station: str | None = None  # Accepte un nom de gare ou un station_id
    max_distance_km: float | None = None
    exclude_paris: bool = False

    def __post_init__(self) -> None:
        """Vérifie la cohérence des critères dès leur création."""
        prefs = (self.culture, self.nature, self.events, self.attractions)
        if any(p < 0 or p > 1 for p in prefs):
            raise ValueError("Les préférences doivent être comprises entre 0 et 1.")
        if sum(prefs) == 0:
            raise ValueError("Au moins une préférence touristique doit être > 0.")
        if self.radius_km not in RADIUSES_KM:
            raise ValueError(f"radius_km doit faire partie de {RADIUSES_KM}.")
        if self.max_distance_km is not None:
            if self.max_distance_km <= 0:
                raise ValueError("max_distance_km doit être strictement positif.")
            if not self.departure_station:
                raise ValueError("Une gare de départ est requise avec max_distance_km.")

    def normalized_preferences(self) -> dict[str, float]:
        """Normalise les poids des 4 préférences pour que leur somme vaille 1."""
        raw = {
            "culture": self.culture,
            "nature": self.nature,
            "events": self.events,
            "attractions": self.attractions,
        }
        total = sum(raw.values())
        return {category: weight / total for category, weight in raw.items()}


class TourismRecommender:
    """Moteur de recommandation de gares basé sur le clustering K-Means."""

    CITY_GROUP_RADIUS_KM = 5.0
    # Évite que les gares proches dominent systématiquement avec leurs scores
    # de fréquentation et de POI.
    DISTANCE_WEIGHT = 0.15

    def __init__(
        self,
        n_clusters: int = 6,
        min_visitors: float = 10_000,
        popularity_weight: float = 0.25,
        favor_poi_with_website: bool = True,
        random_state: int = 42,
    ):
        """Initialise les hyperparamètres internes du modèle de recommandation.

        Paramètres internes :
        - n_clusters : nombre de groupes touristiques (K-Means).
        - min_visitors : seuil minimal de fréquentation annuelle des gares.
        - popularity_weight : poids accordé à la fréquentation dans le score final (0 à 1).
        - favor_poi_with_website : privilégie les compteurs pondérés par présence d'un site web.
        """
        if n_clusters < 2:
            raise ValueError("n_clusters doit être au moins égal à 2.")
        if min_visitors < 0:
            raise ValueError("min_visitors doit être positif ou nul.")
        if not 0 <= popularity_weight <= 1:
            raise ValueError("popularity_weight doit être compris entre 0 et 1.")

        self.n_clusters = n_clusters
        self.min_visitors = min_visitors
        self.popularity_weight = popularity_weight
        self.favor_poi_with_website = favor_poi_with_website
        self.random_state = random_state

        self._stations: pd.DataFrame | None = None
        self._cluster_profiles: pd.DataFrame | None = None

    def _get_feature_column(self, df: pd.DataFrame, prefix: str, radius_km: int) -> str:
        """Retourne la colonne pondérée (site web) si activée et disponible, sinon la brute."""
        weighted_col = f"{prefix}_website_weighted_count_{radius_km}km"
        if self.favor_poi_with_website and weighted_col in df.columns:
            return weighted_col
        return f"{prefix}_count_{radius_km}km"

    def fit(self, stations: pd.DataFrame) -> "TourismRecommender":
        """Entraîne K-Means pour regrouper les gares selon leur profil touristique."""
        # On utilise le rayon de référence de 10 km pour caractériser chaque gare
        ref_columns = {
            cat: self._get_feature_column(stations, prefix, radius_km=10)
            for cat, prefix in CATEGORY_COLUMNS.items()
        }
        missing = set(ref_columns.values()) - set(stations.columns)
        if missing:
            raise ValueError(f"Colonnes manquantes dans stations : {', '.join(sorted(missing))}")

        # Conversion en tableau NumPy avant renommage des colonnes pour éviter les NaN d'alignement
        raw_tourism = (
            stations[list(ref_columns.values())]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0)
            .clip(lower=0)
            .to_numpy()
        )
        tourism_log = pd.DataFrame(
            np.log1p(raw_tourism),
            index=stations.index,
            columns=list(ref_columns.keys()),
        )

        raw_visitors = (
            pd.to_numeric(stations["visitors"], errors="coerce")
            .fillna(0)
            .clip(lower=0)
            .to_numpy()
        )
        popularity_log = pd.Series(
            np.log1p(raw_visitors),
            index=stations.index,
            name="popularity",
        )

        # Standardisation (moyenne 0, écart-type 1) avant K-Means
        features_matrix = pd.concat([tourism_log, popularity_log], axis=1)
        scaled_matrix = StandardScaler().fit_transform(features_matrix)

        kmeans = KMeans(
            n_clusters=min(self.n_clusters, len(stations)),
            n_init=10,
            random_state=self.random_state,
        ).fit(scaled_matrix)

        self._stations = stations.copy()
        self._stations["cluster"] = kmeans.labels_

        # Profil touristique moyen normalisé de chaque cluster (entre 0 et 1)
        normalized_tourism = tourism_log.div(tourism_log.max().replace(0, 1), axis="columns")
        self._cluster_profiles = (
            normalized_tourism.assign(cluster=kmeans.labels_)
            .groupby("cluster")[list(CATEGORY_COLUMNS.keys())]
            .mean()
        )
        return self

    def _resolve_departure_station(self, query: str) -> pd.Series:
        """Recherche la gare de départ par station_id ou par nom exact."""
        assert self._stations is not None
        by_id = self._stations[self._stations["station_id"].astype(str).eq(query)]
        if len(by_id) == 1:
            return by_id.iloc[0]

        by_name = self._stations[self._stations["name"].eq(query)]
        if by_name.empty:
            raise ValueError(f"Gare de départ introuvable : '{query}'.")
        if len(by_name) > 1:
            raise ValueError(f"Plusieurs gares correspondent à '{query}' ; préciser le station_id.")
        return by_name.iloc[0]

    @staticmethod
    def _normalize_station_name(name: object) -> str:
        """Normalise les noms pour relier les données des gares au réseau GTFS."""
        normalized = unicodedata.normalize("NFKD", str(name))
        return (
            normalized.encode("ascii", "ignore")
            .decode()
            .lower()
            .replace("-", " ")
            .strip()
        )

    @classmethod
    def _city_keys(cls, stations: pd.DataFrame) -> pd.Series:
        """Retourne une clé commune aux gares situées dans la même ville."""
        for column in ("city", "commune", "insee"):
            if column in stations.columns:
                values = stations[column].astype("string").str.strip()
                if values.notna().all() and values.ne("").all():
                    return values

        # station_features.csv ne contient pas toujours le code commune.
        # Dans ce cas, les gares d'une même ville sont regroupées spatialement.
        coordinates = np.radians(stations[["lat", "lon"]].to_numpy())
        tree = BallTree(coordinates, metric="haversine")
        neighbours = tree.query_radius(
            coordinates, r=cls.CITY_GROUP_RADIUS_KM / EARTH_RADIUS_KM
        )
        groups = np.arange(len(stations))

        def find(index: int) -> int:
            while groups[index] != index:
                groups[index] = groups[groups[index]]
                index = groups[index]
            return index

        for index, nearby in enumerate(neighbours):
            root = find(index)
            for other in nearby:
                other_root = find(int(other))
                if root != other_root:
                    groups[other_root] = root

        return pd.Series([find(index) for index in range(len(stations))], index=stations.index)

    def recommend(
        self,
        criteria: RecommendationCriteria | None = None,
        n_results: int = 10,
    ) -> pd.DataFrame:
        """Recommande les meilleures gares selon les préférences et le modèle K-Means."""
        if self._stations is None or self._cluster_profiles is None:
            raise RuntimeError("Appeler fit() avant recommend().")
        if n_results <= 0:
            raise ValueError("n_results doit être strictement positif.")

        criteria = criteria or RecommendationCriteria()
        preferences = pd.Series(criteria.normalized_preferences())

        # 1. Filtre interne sur le minimum de fréquentation
        visitors = pd.to_numeric(self._stations["visitors"], errors="coerce").fillna(0)
        candidates = self._stations[visitors.ge(self.min_visitors)].copy()
        if candidates.empty:
            raise ValueError("Aucune gare n'atteint le seuil minimal de fréquentation.")

        # 2. Calcul des distances depuis la gare de départ (si renseignée)
        candidates["distance_from_departure_km"] = np.nan
        if criteria.departure_station:
            departure = self._resolve_departure_station(criteria.departure_station)
            all_rad = np.radians(self._stations[["lat", "lon"]].to_numpy())
            dep_rad = np.radians([[departure["lat"], departure["lon"]]])

            tree = BallTree(all_rad, metric="haversine")
            distances, indices = tree.query(dep_rad, k=len(self._stations))
            dist_by_id = pd.Series(
                distances[0] * EARTH_RADIUS_KM,
                index=self._stations.iloc[indices[0]]["station_id"],
            )

            candidates["distance_from_departure_km"] = candidates["station_id"].map(dist_by_id)
            # Exclusion de la gare de départ elle-même
            candidates = candidates[candidates["station_id"].ne(departure["station_id"])]
            if criteria.max_distance_km is not None:
                candidates = candidates[
                    candidates["distance_from_departure_km"].le(criteria.max_distance_km)
                ]

        # 3. Exclusion optionnelle de Paris / Île-de-France
        if criteria.exclude_paris:
            if "departement" not in candidates.columns:
                raise ValueError("La colonne 'departement' est requise pour exclure Paris.")
            depts = candidates["departement"].astype("string").str.strip()
            candidates = candidates[~depts.isin(PARIS_REGION_DEPARTMENTS)]

        if candidates.empty:
            raise ValueError("Aucune gare ne correspond aux filtres géographiques.")

        # 4. Sélection par Machine Learning : on retient la moitié des clusters les plus pertinents
        cluster_scores = self._cluster_profiles.dot(preferences)
        top_k_clusters = max(1, len(cluster_scores) // 2)
        best_clusters = cluster_scores.nlargest(top_k_clusters).index
        candidates = candidates[candidates["cluster"].isin(best_clusters)].copy()
        if candidates.empty:
            raise ValueError("Aucune gare trouvée dans les clusters correspondants.")

        # 5. Calcul du score touristique dans le rayon choisi par l'utilisateur
        category_scores = pd.DataFrame(index=candidates.index)
        for category, prefix in CATEGORY_COLUMNS.items():
            col = self._get_feature_column(self._stations, prefix, criteria.radius_km)
            if col not in candidates.columns:
                raise ValueError(
                    f"Colonne '{col}' absente : relancer d'abord station_features.py."
                )
            values = np.log1p(pd.to_numeric(candidates[col], errors="coerce").fillna(0).clip(lower=0))
            max_val = (
                np.log1p(pd.to_numeric(self._stations[col], errors="coerce").fillna(0).clip(lower=0)).max()
                or 1.0
            )
            category_scores[category] = values / max_val

        tourism_score = category_scores.dot(preferences)

        # Combinaison avec le facteur interne de fréquentation
        pop_values = np.log1p(
            pd.to_numeric(candidates["visitors"], errors="coerce").fillna(0).clip(lower=0)
        )
        pop_max = (
            np.log1p(pd.to_numeric(self._stations["visitors"], errors="coerce").fillna(0).clip(lower=0)).max()
            or 1.0
        )
        popularity_score = pop_values / pop_max

        base_score = (
            (1 - self.popularity_weight) * tourism_score
            + self.popularity_weight * popularity_score
        )
        if criteria.departure_station:
            distance_scale = (
                criteria.max_distance_km
                or candidates["distance_from_departure_km"].max()
            )
            distance_score = (
                candidates["distance_from_departure_km"] / distance_scale
            ).clip(lower=0, upper=1)
            candidates["recommendation_score"] = (
                (1 - self.DISTANCE_WEIGHT) * base_score
                + self.DISTANCE_WEIGHT * distance_score
            )
        else:
            candidates["recommendation_score"] = base_score
        candidates["cluster_score"] = candidates["cluster"].map(cluster_scores)
        candidates["dominant_category"] = category_scores.mul(preferences).idxmax(axis=1)

        candidates["city_key"] = self._city_keys(candidates)
        return (
            candidates.sort_values(["recommendation_score", "cluster_score"], ascending=False)
            .drop_duplicates("city_key")
            .head(n_results)
            .drop(columns="city_key")
            .reset_index(drop=True)
        )


def get_top_pois_for_recommendations(
    recommendations: pd.DataFrame,
    criteria: RecommendationCriteria,
    pois: pd.DataFrame,
    station_poi_index: pd.DataFrame,
    n_pois: int = 20,
    favor_poi_with_website: bool = True,
) -> pd.DataFrame:
    """Retourne des POI répartis selon les préférences autour de chaque gare."""
    if n_pois <= 0:
        raise ValueError("n_pois doit être strictement positif.")
    if "station_id" not in recommendations.columns:
        raise ValueError("recommendations doit contenir la colonne 'station_id'.")

    prefs = criteria.normalized_preferences()
    website_bonus = 3.0 if favor_poi_with_website else 0.0
    results = []

    for _, station in recommendations.iterrows():
        # Filtrage des liens pré-calculés dans le rayon choisi
        links = station_poi_index[
            station_poi_index["station_id"].eq(station["station_id"])
            & station_poi_index["distance_km"].le(criteria.radius_km)
        ]
        if links.empty:
            continue

        top_pois = links.merge(pois, on="poi_index", how="left")
        top_pois["preference"] = (
            top_pois["category"].map(POI_CATEGORY_BY_TYPE).map(prefs).fillna(0)
        )
        # Score d'attractivité : préférence utilisateur + bonus site web - éloignement
        top_pois["attractivity_score"] = (
            top_pois["preference"] * 10
            + top_pois["has_website"].fillna(False).astype(float) * website_bonus
            - top_pois["distance_km"] / (criteria.radius_km or 1)
        )

        # Répartition proportionnelle aux préférences, avec la méthode du
        # plus fort reste pour distribuer exactement n_pois emplacements.
        category_preferences = pd.Series(prefs)
        quotas_float = category_preferences * n_pois
        quotas = quotas_float.astype(int)
        remaining_slots = n_pois - int(quotas.sum())
        if remaining_slots:
            remainders = (quotas_float - quotas).sort_values(ascending=False)
            quotas.loc[remainders.head(remaining_slots).index] += 1

        selected_parts = []
        for category, quota in quotas.items():
            if quota <= 0:
                continue
            category_pois = top_pois[
                top_pois["category"].map(POI_CATEGORY_BY_TYPE).eq(category)
            ].sort_values(["attractivity_score", "distance_km"], ascending=[False, True])
            selected_parts.append(category_pois.head(int(quota)))

        selected_indexes = (
            pd.concat(selected_parts).index.unique() if selected_parts else pd.Index([])
        )
        remaining_pois = top_pois.drop(index=selected_indexes)
        missing_slots = n_pois - len(selected_indexes)
        if missing_slots > 0:
            selected_parts.append(
                remaining_pois.sort_values(
                    ["attractivity_score", "distance_km"], ascending=[False, True]
                ).head(missing_slots)
            )

        best_for_station = pd.concat(selected_parts).reset_index(drop=True)
        best_for_station.insert(0, "station_name", station["name"])
        results.append(best_for_station)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def main() -> None:
    """Exemple d'exécution du moteur de recommandation."""
    stations = pd.read_csv(
        ROOT / "data" / "station_features.csv",
        dtype={"station_id": "string", "departement": "string"},
    )

    # Critères utilisateur simplifiés
    criteria = RecommendationCriteria(
        culture=1.0,
        nature=0.0,
        events=0.0,
        attractions=0.0,
        radius_km=10,
        departure_station="Nancy",
        max_distance_km=100,
        exclude_paris=True,
    )

    # Paramètres internes du moteur (fréquentation minimale, poids popularité, sites web)
    recommender = TourismRecommender(
        n_clusters=6,
        min_visitors=10_000,
        popularity_weight=0.25,
        favor_poi_with_website=True,
    ).fit(stations)

    recommendations = recommender.recommend(criteria, n_results=5)
    print(recommendations[["name", "recommendation_score", "dominant_category"]])

    pois = load_pois()
    station_poi_index = pd.read_csv(
        ROOT / "data" / "station_poi_index.csv",
        dtype={"station_id": "string"},
    )
    top_pois = get_top_pois_for_recommendations(
        recommendations,
        criteria,
        pois,
        station_poi_index,
        n_pois=20,
        favor_poi_with_website=recommender.favor_poi_with_website,
    )
    print(
        top_pois[["station_name", "Nom", "category", "distance_km", "attractivity_score"]]
    )


if __name__ == "__main__":
    main()