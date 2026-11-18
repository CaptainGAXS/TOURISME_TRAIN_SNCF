from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.neighbors import BallTree
from sklearn.preprocessing import StandardScaler


# Racine du projet et correspondance entre préférences et fichiers de POI.
ROOT = Path(__file__).resolve().parent.parent.parent
CATEGORY_COLUMNS = {
    "culture": "hpoi",
    "nature": "npoi",
    "events": "epoi",
    "attractions": "attraction",
}
RADIUSES_KM = (20, 15, 10, 5, 3, 1)
POI_CATEGORY_BY_TYPE = {
    "hpoi": "culture",
    "npoi": "nature",
    "epoi": "events",
    "attraction": "attractions",
}
# Départements composant la région Île-de-France.
ILE_DE_FRANCE_DEPARTMENTS = frozenset(
    {"75", "77", "78", "91", "92", "93", "94", "95"}
)


@dataclass(frozen=True)
class RecommendationCriteria:
    """Paramètres utilisés pour filtrer et classer les destinations."""

    culture: float = 0.25
    nature: float = 0.25
    events: float = 0.25
    attractions: float = 0.25
    radius_km: int = 10
    prefer_popular: float = 0.25
    min_visitors: float = 0
    n_results: int = 10
    departure_station_id: str | None = None
    departure_station_name: str | None = None
    max_distance_km: float | None = None
    exclude_ile_de_france: bool = False
    favor_poi_with_website: bool = True

    def preferences(self) -> dict[str, float]:
        """Valide et normalise les préférences touristiques."""
        values = {
            "culture": self.culture,
            "nature": self.nature,
            "events": self.events,
            "attractions": self.attractions,
        }
        if any(value < 0 or value > 1 for value in values.values()):
            raise ValueError("Preferences must be between 0 and 1")
        if sum(values.values()) == 0:
            raise ValueError("At least one tourism preference must be positive")
        if self.radius_km not in RADIUSES_KM:
            raise ValueError(f"radius_km must be one of {RADIUSES_KM}")
        if not 0 <= self.prefer_popular <= 1:
            raise ValueError("prefer_popular must be between 0 and 1")
        if self.n_results <= 0:
            raise ValueError("n_results must be positive")
        if self.departure_station_id and self.departure_station_name:
            raise ValueError(
                "Provide only one of departure_station_id or departure_station_name"
            )
        if self.max_distance_km is not None:
            if self.max_distance_km <= 0:
                raise ValueError("max_distance_km must be positive")
            if not self.departure_station_id and not self.departure_station_name:
                raise ValueError(
                    "A departure station is required with max_distance_km"
                )
        # La somme vaut 1 pour rendre les scores comparables.
        total = sum(values.values())
        return {name: value / total for name, value in values.items()}


class TourismRecommender:
    """Regroupe les gares puis les classe selon les préférences utilisateur."""

    def __init__(self, n_clusters: int = 6, random_state: int = 42):
        if n_clusters < 2:
            raise ValueError("n_clusters must be at least 2")
        self.n_clusters = n_clusters
        self.random_state = random_state
        self._stations = None
        self._model = None
        self._cluster_profiles: pd.DataFrame | None = None

    def fit(self, stations: pd.DataFrame) -> "TourismRecommender":
        """Entraîne K-Means sur les features touristiques des gares."""
        # Les compteurs à 10 km décrivent le profil touristique de chaque gare.
        category_columns = {
            category: (
                f"{prefix}_website_weighted_count_10km"
                if f"{prefix}_website_weighted_count_10km" in stations
                else f"{prefix}_count_10km"
            )
            for category, prefix in CATEGORY_COLUMNS.items()
        }
        missing = set(category_columns.values()) - set(stations.columns)
        if missing:
            raise ValueError(
                f"Missing station features: {', '.join(sorted(missing))}"
            )

        model_data = stations.copy()
        tourism_columns = list(category_columns.values())
        tourism_values = pd.DataFrame(
            np.log1p(model_data[tourism_columns].fillna(0)),
            index=model_data.index,
            columns=tourism_columns,
        )
        popularity = pd.Series(
            np.log1p(model_data["visitors"].fillna(0).clip(lower=0)),
            index=model_data.index,
            name="popularity",
        )
        matrix = pd.concat([tourism_values, popularity], axis=1)

        # La standardisation évite que la fréquentation domine les autres données.
        scaled_matrix = StandardScaler().fit_transform(matrix)
        self._model = KMeans(
            n_clusters=min(self.n_clusters, len(model_data)),
            n_init=10,
            random_state=self.random_state,
        ).fit(scaled_matrix)

        self._stations = model_data.copy()
        self._stations["cluster"] = self._model.labels_

        # Le profil moyen de chaque cluster sert à sélectionner les clusters
        # correspondant le mieux aux préférences de l'utilisateur.
        normalized = tourism_values.div(
            tourism_values.max().replace(0, 1), axis="columns"
        )
        normalized.columns = list(category_columns.keys())
        self._cluster_profiles = normalized.assign(
            cluster=self._model.labels_
        ).groupby("cluster")[list(category_columns)].mean()
        return self

    def recommend(
        self, criteria: RecommendationCriteria | None = None
    ) -> pd.DataFrame:
        """Retourne les meilleures gares selon les critères fournis."""
        if self._stations is None:
            raise RuntimeError("Call fit() before recommend()")
        criteria = criteria or RecommendationCriteria()
        preferences = criteria.preferences()

        # Première sélection : fréquentation minimale de la gare.
        candidates = self._stations[
            self._stations["visitors"].fillna(0).ge(criteria.min_visitors)
        ].copy()
        if candidates.empty:
            raise ValueError("No station matches min_visitors")

        # La distance de départ est calculée uniquement si une gare est fournie.
        candidates["distance_from_departure_km"] = np.nan
        if criteria.departure_station_id or criteria.departure_station_name:
            if criteria.departure_station_id:
                departure_matches = self._stations[
                    self._stations["station_id"].eq(criteria.departure_station_id)
                ]
            else:
                departure_station_name = criteria.departure_station_name
                assert departure_station_name is not None
                departure_matches = self._stations[
                    self._stations["name"].eq(departure_station_name)
                ]
            if departure_matches.empty:
                raise ValueError("Departure station not found")
            if len(departure_matches) > 1:
                raise ValueError(
                    "departure_station_name matches several stations; "
                    "use departure_station_id"
                )

            departure = departure_matches.iloc[0]
            # BallTree utilise la distance haversine sur des coordonnées en radians.
            station_coordinates = np.radians(
                self._stations[["lat", "lon"]].to_numpy()
            )
            departure_coordinates = np.radians(
                [[departure["lat"], departure["lon"]]]
            )
            station_tree = BallTree(station_coordinates, metric="haversine")
            distances, indices = station_tree.query(
                departure_coordinates, k=len(self._stations)
            )
            distances_km = distances[0] * 6371.0088
            station_distances = pd.Series(
                distances_km,
                index=self._stations.iloc[indices[0]]["station_id"],
            )
            candidates["distance_from_departure_km"] = candidates[
                "station_id"
            ].map(station_distances)
            if criteria.max_distance_km is not None:
                candidates = candidates[
                    candidates["distance_from_departure_km"].le(
                        criteria.max_distance_km
                    )
                ]
            candidates = candidates[
                candidates["station_id"].ne(departure["station_id"])
            ]
        elif criteria.max_distance_km is not None:
            raise ValueError("A departure station is required with max_distance_km")

        if criteria.exclude_ile_de_france:
            if "departement" not in candidates:
                raise ValueError("The departement column is required for this filter")
            departments = (
                candidates["departement"]
                .astype("string")
                .str.strip()
            )
            candidates = candidates[
                ~departments.isin(ILE_DE_FRANCE_DEPARTMENTS)
            ]

        if candidates.empty:
            raise ValueError("No destination station matches the search scope")

        # K-Means réduit l'espace de recherche aux clusters les plus adaptés.
        preference_vector = pd.Series(preferences)
        cluster_profiles = self._cluster_profiles
        if cluster_profiles is None:
            raise RuntimeError("Call fit() before recommend()")
        cluster_scores = cluster_profiles.dot(preference_vector)
        cluster_count = max(1, len(cluster_scores) // 2)
        selected_clusters = cluster_scores.nlargest(cluster_count).index
        candidates = candidates[candidates["cluster"].isin(selected_clusters)].copy()
        if candidates.empty:
            raise ValueError("No station matches the requested preferences")

        # Score touristique normalisé pour chaque catégorie choisie.
        category_scores = pd.DataFrame(index=candidates.index)
        for category, prefix in CATEGORY_COLUMNS.items():
            weighted_column = (
                f"{prefix}_website_weighted_count_{criteria.radius_km}km"
            )
            column = (
                weighted_column
                if criteria.favor_poi_with_website
                and weighted_column in self._stations
                else f"{prefix}_count_{criteria.radius_km}km"
            )
            values = np.log1p(candidates[column].fillna(0))
            maximum = np.log1p(self._stations[column].fillna(0)).max()
            category_scores[category] = values / (maximum or 1)

        tourism_score = category_scores.dot(preference_vector)
        # La fréquentation peut compléter les préférences sans les remplacer.
        popularity_values = np.log1p(candidates["visitors"].fillna(0).clip(lower=0))
        popularity_score = popularity_values / (
            np.log1p(self._stations["visitors"].fillna(0).clip(lower=0)).max() or 1
        )
        candidates["recommendation_score"] = (
            (1 - criteria.prefer_popular) * tourism_score
            + criteria.prefer_popular * popularity_score
        )
        candidates["cluster_score"] = candidates["cluster"].map(cluster_scores)
        # Cette colonne explique la raison principale de la recommandation.
        candidates["dominant_category"] = category_scores.mul(
            preference_vector
        ).idxmax(axis=1)
        return (
            candidates.sort_values(
                ["recommendation_score", "cluster_score"],
                ascending=False,
            )
            .head(criteria.n_results)
            .reset_index(drop=True)
        )


def get_top_pois_for_station(
    station_id: str,
    criteria: RecommendationCriteria,
    pois: pd.DataFrame,
    station_poi_index: pd.DataFrame,
    n_pois: int = 5,
) -> pd.DataFrame:
    """Retourne les meilleurs POI correspondant à une gare recommandée."""
    if n_pois <= 0:
        raise ValueError("n_pois must be positive")

    # On prend les liens gare-POI déjà calculés, puis on limite au rayon choisi.
    links = station_poi_index[
        station_poi_index["station_id"].eq(station_id)
        & station_poi_index["distance_km"].le(criteria.radius_km)
    ].copy()
    if links.empty:
        return pd.DataFrame()

    # On récupère les informations détaillées du POI (catégorie, site internet).
    top_pois = links.merge(pois, on="poi_index", how="left")
    top_pois["preference"] = top_pois["category"].map(
        {
            poi_type: getattr(criteria, preference)
            for poi_type, preference in POI_CATEGORY_BY_TYPE.items()
        }
    ).fillna(0)

    # Un site internet augmente légèrement l'attractivité du POI.
    top_pois["attractivity_score"] = (
        top_pois["preference"] * 10
        + top_pois["has_website"].fillna(False).astype(float) * 3
        - top_pois["distance_km"] / (criteria.radius_km or 1)
    )
    return (
        top_pois.sort_values(
            ["attractivity_score", "distance_km"],
            ascending=[False, True],
        )
        .head(n_pois)
        .reset_index(drop=True)
    )


def get_top_pois_for_recommendations(
    recommendations: pd.DataFrame,
    criteria: RecommendationCriteria,
    pois: pd.DataFrame,
    station_poi_index: pd.DataFrame,
    n_pois: int = 5,
) -> pd.DataFrame:
    """Ajoute les cinq meilleurs POI liés à chaque gare recommandée."""
    if "station_id" not in recommendations:
        raise ValueError("recommendations must contain station_id")

    station_results = []
    for _, recommendation in recommendations.iterrows():
        top_pois = get_top_pois_for_station(
            str(recommendation["station_id"]),
            criteria,
            pois,
            station_poi_index,
            n_pois,
        )
        if top_pois.empty:
            continue
        top_pois.insert(0, "station_name", recommendation["name"])
        station_results.append(top_pois)

    if not station_results:
        return pd.DataFrame()
    return pd.concat(station_results, ignore_index=True)


def main() -> None:
    """Exemple d'utilisation du moteur de recommandation."""
    stations = pd.read_csv(ROOT / "data" / "station_features.csv")
    criteria = RecommendationCriteria(
        culture=0.1,
        nature=0.8,
        events=0.2,
        attractions=0.2,
        radius_km=10,
        departure_station_name="Nancy",
        max_distance_km=300,
        n_results=5,
        exclude_ile_de_france=True,
    )
    recommender = TourismRecommender().fit(stations)
    recommendations = recommender.recommend(criteria)
    print(recommendations[["name", "recommendation_score", "dominant_category"]])

    from scripts.research.station_features import load_pois

    pois = load_pois()
    station_poi_index = pd.read_csv(
        ROOT / "data" / "station_poi_index.csv"
    )
    top_pois = get_top_pois_for_recommendations(
        recommendations,
        criteria,
        pois,
        station_poi_index,
        n_pois=5,
    )
    print(
        top_pois[
            ["station_name", "Nom", "category", "distance_km",
             "attractivity_score"]
        ]
    )


if __name__ == "__main__":
    main()
