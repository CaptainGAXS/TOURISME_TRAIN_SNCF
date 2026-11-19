from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree, NearestNeighbors

from scripts.research.station_features import (
    EARTH_RADIUS_KM,
    RADIUSES_KM,
    ROOT,
    load_pois,
)

CATEGORY_COLUMNS = {
    "patrimoine": "hpoi",
    "nature": "npoi",
    "events": "epoi",
    "attractions": "attraction",
}
POI_CATEGORY_BY_TYPE = {prefix: cat for cat, prefix in CATEGORY_COLUMNS.items()}
PARIS_REGION_DEPARTMENTS = frozenset({"75", "77", "78", "91", "92", "93", "94", "95"})


@dataclass(frozen=True)
class RecommendationCriteria:
    """Critères de recherche de l'utilisateur."""

    patrimoine: float = 0.25
    nature: float = 0.25
    events: float = 0.25
    attractions: float = 0.25
    radius_km: int = 5
    departure_station: str | None = None
    max_distance_km: float | None = None
    exclude_paris: bool = False
    event_date: date | None = None

    def __post_init__(self) -> None:
        prefs = (self.patrimoine, self.nature, self.events, self.attractions)
        if any(p < 0 or p > 1 for p in prefs):
            raise ValueError("Les préférences doivent être comprises entre 0 et 1.")
        if sum(prefs) == 0:
            raise ValueError("Au moins une préférence doit être strictement positive.")
        if self.radius_km not in RADIUSES_KM:
            raise ValueError(f"radius_km doit être dans {RADIUSES_KM}.")
        if self.max_distance_km is not None:
            if self.max_distance_km <= 0:
                raise ValueError("max_distance_km doit être > 0.")
            if not self.departure_station:
                raise ValueError("departure_station est obligatoire si max_distance_km est défini.")

    def normalized_preferences(self) -> dict[str, float]:
        """Normalise les poids pour que leur somme soit égale à 1."""
        raw = {
            "patrimoine": self.patrimoine,
            "nature": self.nature,
            "events": self.events,
            "attractions": self.attractions,
        }
        total = sum(raw.values())
        return {k: v / total for k, v in raw.items()}


class TourismRecommender:
    """Moteur de recommandation ML basé sur la similarité cosinus (KNN) et le rang percentile."""

    CITY_GROUP_RADIUS_KM = 5.0
    DISTANCE_WEIGHT = 0.15

    def __init__(
        self,
        min_visitors: float = 10_000,
        popularity_weight: float = 0.20,
        favor_poi_with_website: bool = True,
    ):
        if min_visitors < 0:
            raise ValueError("min_visitors doit être >= 0.")
        if not 0 <= popularity_weight <= 1:
            raise ValueError("popularity_weight doit être entre 0 et 1.")

        self.min_visitors = min_visitors
        self.popularity_weight = popularity_weight
        self.favor_poi_with_website = favor_poi_with_website

        self._stations: pd.DataFrame | None = None
        self._ball_tree: BallTree | None = None
        # Stocke les matrices de features normalisées (rang percentile) par rayon
        self._feature_matrices: dict[int, pd.DataFrame] = {}

    def _get_col_name(self, df: pd.DataFrame, prefix: str, radius_km: int) -> str:
        """Sélectionne la colonne brute ou pondérée (site web), sauf pour les événements."""
        weighted_col = f"{prefix}_website_weighted_count_{radius_km}km"
        # On évite de pénaliser les événements qui ont rarement un site web dédié
        if self.favor_poi_with_website and prefix != "epoi" and weighted_col in df.columns:
            return weighted_col
        return f"{prefix}_count_{radius_km}km"

    def fit(self, stations: pd.DataFrame) -> "TourismRecommender":
        """Prépare l'index spatial et les vecteurs normalisés de chaque gare pour tous les rayons."""
        visitors = pd.to_numeric(stations["visitors"], errors="coerce").fillna(0)
        valid_stations = stations[visitors.ge(self.min_visitors)].copy().reset_index(drop=True)

        if valid_stations.empty:
            raise ValueError("Aucune gare n'atteint le seuil min_visitors.")

        # 1. Index spatial BallTree pour des calculs de distance instantanés
        coords_rad = np.radians(valid_stations[["lat", "lon"]].to_numpy())
        self._ball_tree = BallTree(coords_rad, metric="haversine")

        # 2. Score de popularité normalisé par rang percentile [0, 1]
        valid_stations["popularity_score"] = (
            pd.to_numeric(valid_stations["visitors"], errors="coerce")
            .fillna(0)
            .rank(pct=True)
        )

        # 3. Calcul des vecteurs touristiques normalisés par rang percentile pour chaque rayon
        self._feature_matrices.clear()
        for radius in RADIUSES_KM:
            matrix = pd.DataFrame(index=valid_stations.index)
            for category, prefix in CATEGORY_COLUMNS.items():
                col = self._get_col_name(valid_stations, prefix, radius)
                if col in valid_stations.columns:
                    raw_vals = pd.to_numeric(valid_stations[col], errors="coerce").fillna(0).clip(lower=0)
                    # Les gares avec 0 POI gardent strictement 0.0 ; les autres sont classées par percentile
                    ranked = raw_vals.rank(pct=True)
                    matrix[category] = np.where(raw_vals > 0, ranked, 0.0)
            if len(matrix.columns) == len(CATEGORY_COLUMNS):
                self._feature_matrices[radius] = matrix

        if not self._feature_matrices:
            raise ValueError("Aucune colonne de POI valide trouvée dans le dataset stations.")

        self._stations = valid_stations
        return self

    def _resolve_departure(self, query: str) -> pd.Series:
        """Retrouve la gare de départ par station_id ou par nom exact."""
        assert self._stations is not None
        by_id = self._stations[self._stations["station_id"].astype(str).eq(query)]
        if len(by_id) == 1:
            return by_id.iloc[0]

        by_name = self._stations[self._stations["name"].eq(query)]
        if by_name.empty:
            raise ValueError(f"Gare de départ introuvable : '{query}'.")
        if len(by_name) > 1:
            raise ValueError(f"Plusieurs gares portent le nom '{query}', utilisez station_id.")
        return by_name.iloc[0]

    @classmethod
    def _deduplicate_by_city(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Ne garde que la meilleure gare par ville (regroupement par commune ou rayon de 5 km)."""
        if df.empty:
            return df

        for col in ("city", "commune", "insee"):
            if col in df.columns:
                keys = df[col].astype("string").str.strip()
                if keys.notna().all() and keys.ne("").all():
                    return df.drop_duplicates(subset=[col])

        coords = np.radians(df[["lat", "lon"]].to_numpy())
        tree = BallTree(coords, metric="haversine")
        neighbours = tree.query_radius(coords, r=cls.CITY_GROUP_RADIUS_KM / EARTH_RADIUS_KM)

        kept_indices = []
        visited = set()
        # df est déjà trié par score décroissant : le premier rencontré dans un rayon de 5 km est le meilleur
        for idx, nearby in enumerate(neighbours):
            if idx not in visited:
                kept_indices.append(idx)
                visited.update(nearby)

        return df.iloc[kept_indices]

    def recommend(
        self,
        criteria: RecommendationCriteria | None = None,
        n_results: int = 5,
    ) -> pd.DataFrame:
        """Recommande les n_results meilleures gares via similarité cosinus + scoring hybride."""
        if self._stations is None or self._ball_tree is None:
            raise RuntimeError("Appelez fit() avant recommend().")
        if n_results <= 0:
            raise ValueError("n_results doit être > 0.")

        criteria = criteria or RecommendationCriteria()
        if criteria.radius_km not in self._feature_matrices:
            raise ValueError(f"Données manquantes pour le rayon {criteria.radius_km} km.")

        candidates = self._stations.copy()
        features = self._feature_matrices[criteria.radius_km].copy()

        # --- ÉTAPE 1 : Filtres géographiques ---
        candidates["distance_from_departure_km"] = np.nan
        if criteria.departure_station:
            dep = self._resolve_departure(criteria.departure_station)
            dep_rad = np.radians([[dep["lat"], dep["lon"]]])
            distances, indices = self._ball_tree.query(dep_rad, k=len(self._stations))

            dist_series = pd.Series(distances[0] * EARTH_RADIUS_KM, index=indices[0])
            candidates["distance_from_departure_km"] = dist_series

            # Exclure la gare de départ elle-même
            mask = candidates["station_id"].ne(dep["station_id"])
            if criteria.max_distance_km is not None:
                mask &= candidates["distance_from_departure_km"].le(criteria.max_distance_km)
            candidates = candidates[mask]

        if criteria.exclude_paris:
            if "departement" not in candidates.columns:
                raise ValueError("Colonne 'departement' manquante pour exclure l'Île-de-France.")
            depts = candidates["departement"].astype("string").str.strip()
            candidates = candidates[~depts.isin(PARIS_REGION_DEPARTMENTS)]

        if candidates.empty:
            raise ValueError("Aucune gare ne correspond aux contraintes géographiques.")

        # --- ÉTAPE 2 : Modèle ML (NearestNeighbors avec Similarité Cosinus) ---
        prefs_dict = criteria.normalized_preferences()
        categories = list(CATEGORY_COLUMNS.keys())
        user_vector = np.array([[prefs_dict[cat] for cat in categories]])

        candidate_features = features.loc[candidates.index, categories]

        # On entraîne le modèle KNN sur l'espace des gares candidates
        knn = NearestNeighbors(n_neighbors=len(candidates), metric="cosine")
        knn.fit(candidate_features.to_numpy())
        cosine_distances, neighbor_indices = knn.kneighbors(user_vector)

        # Similarité cosinus = 1 - distance cosinus (entre 0 et 1)
        cosine_sim = np.clip(1.0 - cosine_distances[0], 0.0, 1.0)
        ordered_idx = candidates.index[neighbor_indices[0]]

        candidates = candidates.loc[ordered_idx].copy()
        ordered_features = candidate_features.loc[ordered_idx]
        candidates["profile_alignment"] = cosine_sim

        # --- ÉTAPE 3 : Intensité touristique et score final ---
        # Le cosinus mesure l'orientation du profil (ex: 100% nature) ;
        # intensity mesure le volume d'offre disponible dans les catégories demandées.
        prefs_series = pd.Series(prefs_dict)
        intensity = ordered_features.dot(prefs_series)

        # Combinaison géométrique entre alignement du profil et richesse de l'offre
        tourism_score = np.sqrt(candidates["profile_alignment"] * intensity)

        base_score = (
            (1.0 - self.popularity_weight) * tourism_score
            + self.popularity_weight * candidates["popularity_score"]
        )

        if criteria.departure_station:
            max_dist = criteria.max_distance_km or candidates["distance_from_departure_km"].max() or 1.0
            dist_bonus = (candidates["distance_from_departure_km"] / max_dist).clip(0.0, 1.0)
            candidates["recommendation_score"] = (
                (1.0 - self.DISTANCE_WEIGHT) * base_score
                + self.DISTANCE_WEIGHT * dist_bonus
            )
        else:
            candidates["recommendation_score"] = base_score

        candidates["dominant_category"] = ordered_features.mul(prefs_series).idxmax(axis=1)

        # --- ÉTAPE 4 : Tri, dédoublonnage par ville et sélection du Top N ---
        candidates = candidates.sort_values("recommendation_score", ascending=False)
        candidates = self._deduplicate_by_city(candidates)

        return candidates.head(n_results).reset_index(drop=True)


def get_top_pois_for_recommendations(
    recommendations: pd.DataFrame,
    criteria: RecommendationCriteria,
    pois: pd.DataFrame,
    station_poi_index: pd.DataFrame,
    n_pois: int = 20,
    favor_poi_with_website: bool = True,
) -> pd.DataFrame:
    """Sélectionne les n_pois meilleurs POI autour de chaque gare recommandée,
    en respectant strictement la répartition des préférences de l'utilisateur
    et en favorisant la proximité avec la gare."""
    if n_pois <= 0:
        raise ValueError("n_pois doit être > 0.")
    if recommendations.empty:
        return pd.DataFrame()

    prefs = criteria.normalized_preferences()
    allowed_categories = {cat for cat, weight in prefs.items() if weight > 0}
    results = []

    # Calcul des quotas exacts par catégorie (méthode du plus fort reste)
    prefs_series = pd.Series(prefs)
    exact_quotas = prefs_series * n_pois
    base_quotas = exact_quotas.astype(int)
    remainder_slots = n_pois - int(base_quotas.sum())
    if remainder_slots > 0:
        top_remainders = (exact_quotas - base_quotas).sort_values(ascending=False).head(remainder_slots).index
        base_quotas.loc[top_remainders] += 1

    for _, station in recommendations.iterrows():
        # 1. Récupération des POI dans le rayon demandé autour de la gare
        links = station_poi_index[
            station_poi_index["station_id"].eq(station["station_id"])
            & station_poi_index["distance_km"].le(criteria.radius_km)
        ]
        if links.empty:
            continue

        station_pois = links.merge(pois, on="poi_index", how="inner")
        station_pois["mapped_category"] = station_pois["category"].map(POI_CATEGORY_BY_TYPE)

        # 2. Filtrage sur les catégories choisies par l'utilisateur
        station_pois = station_pois[station_pois["mapped_category"].isin(allowed_categories)].copy()
        if station_pois.empty:
            continue

        # 3. Filtrage temporel si une date d'événement est précisée
        if criteria.event_date is not None:
            is_event = station_pois["mapped_category"].eq("events")
            if is_event.any():
                target = pd.Timestamp(criteria.event_date).date()
                starts = pd.to_datetime(
                    station_pois["Date début"].astype("string").str.slice(0, 10), errors="coerce"
                ).dt.date
                ends = pd.to_datetime(
                    station_pois["Date fin"].astype("string").str.slice(0, 10), errors="coerce"
                ).dt.date.fillna(starts)

                valid_event = starts.notna() & ends.notna() & starts.le(target) & ends.ge(target)
                station_pois = station_pois[~is_event | valid_event].copy()
                if station_pois.empty:
                    continue

        # 4. Calcul du score d'attractivité du POI (proximité + site web + poids préférence)
        has_web = station_pois["has_website"].fillna(False).astype(float)
        # On n'applique le bonus site web qu'aux catégories permanentes (pas aux événements)
        web_bonus = np.where(
            favor_poi_with_website & station_pois["mapped_category"].ne("events"),
            has_web * 2.0,
            0.0,
        )
        # Score de proximité entre 0 (en bordure de rayon) et 3 (au pied de la gare)
        proximity_score = (1.0 - (station_pois["distance_km"] / (criteria.radius_km or 1))).clip(0.0, 1.0) * 3.0
        pref_score = station_pois["mapped_category"].map(prefs) * 5.0

        station_pois["attractivity_score"] = pref_score + proximity_score + web_bonus

        # 5. Sélection selon les quotas de répartition
        selected_chunks = []
        for category, quota in base_quotas.items():
            if quota <= 0:
                continue
            category = str(category)
            cat_subset = station_pois[station_pois["mapped_category"].eq(category)].sort_values(
                by=["attractivity_score", "distance_km"],
                ascending=[False, True],
            )
            selected_chunks.append(cat_subset.head(int(quota)))

        selected_df = pd.concat(selected_chunks) if selected_chunks else pd.DataFrame()

        # 6. Si une catégorie manquait de POI autour de cette gare, on complète avec les meilleurs restants
        missing_count = n_pois - len(selected_df)
        if missing_count > 0:
            remaining_pois = station_pois.drop(index=selected_df.index).sort_values(
                by=["attractivity_score", "distance_km"],
                ascending=[False, True],
            )
            selected_df = pd.concat([selected_df, remaining_pois.head(missing_count)])

        selected_df = selected_df.drop(columns=["mapped_category"]).reset_index(drop=True)
        selected_df.insert(0, "station_name", station["name"])
        results.append(selected_df)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def main() -> None:
    """Exemple d'exécution complet."""
    stations = pd.read_csv(
        ROOT / "data" / "station_features.csv",
        dtype={"station_id": "string", "departement": "string"},
    )

    criteria = RecommendationCriteria(
        patrimoine=1.0,
        nature=0.0,
        events=0.0,
        attractions=0.0,
        radius_km=10,
        departure_station="Nancy",
        max_distance_km=100,
        exclude_paris=True,
    )

    recommender = TourismRecommender(
        min_visitors=10_000,
        popularity_weight=0.20,
        favor_poi_with_website=True,
    ).fit(stations)

    recommendations = recommender.recommend(criteria, n_results=5)
    print("=== TOP 5 GARES RECOMMANDÉES ===")
    print(
        recommendations[
            ["name", "distance_from_departure_km", "recommendation_score", "dominant_category"]
        ]
    )

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
    print("\n=== TOP POI PAR GARE ===")
    print(
        top_pois[["station_name", "Nom", "category", "distance_km", "attractivity_score"]]
    )


if __name__ == "__main__":
    main()