from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.neighbors import BallTree
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parent.parent.parent
CATEGORY_COLUMNS = {
    "culture": "hpoi",
    "nature": "npoi",
    "events": "epoi",
    "attractions": "attraction",
}
RADIUSES_KM = (20, 15, 10, 5, 3, 1)
ILE_DE_FRANCE_DEPARTMENTS = frozenset(
    {"75", "77", "78", "91", "92", "93", "94", "95"}
)


@dataclass(frozen=True)
class RecommendationCriteria:
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

    def preferences(self) -> dict[str, float]:
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
        total = sum(values.values())
        return {name: value / total for name, value in values.items()}


class TourismRecommender:
    """Cluster stations, then rank them according to user preferences."""

    def __init__(self, n_clusters: int = 6, random_state: int = 42):
        if n_clusters < 2:
            raise ValueError("n_clusters must be at least 2")
        self.n_clusters = n_clusters
        self.random_state = random_state
        self._stations = None
        self._category_columns = None
        self._scaler = None
        self._model = None
        self._cluster_profiles: pd.DataFrame | None = None

    def fit(self, stations: pd.DataFrame) -> "TourismRecommender":
        category_columns = {
            category: f"{prefix}_count_10km"
            for category, prefix in CATEGORY_COLUMNS.items()
        }
        missing = set(category_columns.values()) - set(stations.columns)
        if missing:
            raise ValueError(
                f"Missing station features: {', '.join(sorted(missing))}"
            )

        model_data = stations.copy()
        tourism_columns = list(category_columns.values())
        tourism_values: pd.DataFrame = pd.DataFrame(
            np.log1p(model_data[tourism_columns].fillna(0)),
            index=model_data.index,
            columns=tourism_columns,
        )
        popularity: pd.Series = pd.Series(
            np.log1p(model_data["visitors"].fillna(0).clip(lower=0)),
            index=model_data.index,
            name="popularity",
        )
        matrix = pd.concat([tourism_values, popularity.rename("popularity")], axis=1)

        self._scaler = StandardScaler()
        scaled_matrix = self._scaler.fit_transform(matrix)
        self._model = KMeans(
            n_clusters=min(self.n_clusters, len(model_data)),
            n_init=10,
            random_state=self.random_state,
        ).fit(scaled_matrix)

        self._stations = model_data.copy()
        self._stations["cluster"] = self._model.labels_
        self._category_columns = category_columns

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
        if self._stations is None:
            raise RuntimeError("Call fit() before recommend()")
        criteria = criteria or RecommendationCriteria()
        preferences = criteria.preferences()

        candidates = self._stations[
            self._stations["visitors"].fillna(0).ge(criteria.min_visitors)
        ].copy()
        if candidates.empty:
            raise ValueError("No station matches min_visitors")

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
            if "insee" not in candidates:
                raise ValueError("The insee column is required for this filter")
            insee_departments = (
                candidates["insee"]
                .astype("string")
                .str.strip()
                .str.zfill(5)
                .str[:2]
            )
            candidates = candidates[
                ~insee_departments.isin(ILE_DE_FRANCE_DEPARTMENTS)
            ]

        if candidates.empty:
            raise ValueError("No destination station matches the search scope")

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

        category_scores = pd.DataFrame(index=candidates.index)
        for category, prefix in CATEGORY_COLUMNS.items():
            column = f"{prefix}_count_{criteria.radius_km}km"
            values = np.log1p(candidates[column].fillna(0))
            maximum = np.log1p(self._stations[column].fillna(0)).max()
            category_scores[category] = values / (maximum or 1)

        tourism_score = category_scores.dot(preference_vector)
        popularity_values = np.log1p(candidates["visitors"].fillna(0).clip(lower=0))
        popularity_score = popularity_values / (
            np.log1p(self._stations["visitors"].fillna(0).clip(lower=0)).max() or 1
        )
        candidates["recommendation_score"] = (
            (1 - criteria.prefer_popular) * tourism_score
            + criteria.prefer_popular * popularity_score
        )
        candidates["cluster_score"] = candidates["cluster"].map(cluster_scores)
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


def main() -> None:
    stations = pd.read_csv(ROOT / "data" / "station_features.csv")
    recommender = TourismRecommender().fit(stations)
    recommendations = recommender.recommend(
        RecommendationCriteria(
            culture=0.1,
            nature=0.1,
            events=0.2,
            attractions=0.9,
            radius_km=10,
            departure_station_name="Nancy",
            max_distance_km=300,
            n_results=5,
    )
    )
    print(recommendations[["name", "recommendation_score", "dominant_category"]])


if __name__ == "__main__":
    main()
