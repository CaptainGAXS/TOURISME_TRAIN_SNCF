# Tourisme Train SNCF

Projet d'exploitation de données ferroviaires et touristiques en France.
L'objectif est de proposer des recommandations de destinations touristiques à partir d'une gare de départ, en utilisant les données de fréquentation des gares SNCF et les points d'intérêt touristiques.

## Installation

Depuis la racine du projet, créer un environnement virtuel puis l'activer :

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Sous Windows (PowerShell) :

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

Installer les dépendances :

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Préparer les données

Les données déjà préparées se trouvent dans [`data/`](data/). Pour télécharger les
fichiers sources et reconstruire les données (afin d'avoir les dernières versions), consulter
[`scripts/data_prep/DATA.md`](scripts/data_prep/DATA.md), puis exécuter les
commandes indiquées depuis la racine du projet.

En particulier, ce document explique comment :

- télécharger les données des gares et de leur fréquentation ;
- générer [`data/stations.csv`](data/stations.csv) avec `build_stations.py` ;
- télécharger les données touristiques ;
- générer les fichiers de points d'intérêt (`attractions_france.csv`,
  `hpoi.csv`, `npoi.csv` et `epoi.csv`) avec
  `pre-traitement-tourism.py`.
- reconstruire le fichier [`data/station_transfers.csv`](data/station_transfers.csv) avec `build_station_transfers.py` ;
- télécharger le fichier GTFS de la SNCF pour le planificateur d'itinéraire
- construire station_poi_index.csv et poi_nearest_station.csv avec `build_proximity_indexes.py`.
- construire les features gare-POI avec `station_features.py`.

Les identifiants utilisés pendant la préparation sont lus comme du texte afin
de conserver leurs zéros initiaux.

## Lancer le programme

Avec l'environnement virtuel activé :

```bash
streamlit run main.py
```

Pour quitter l'environnement virtuel :

```bash
deactivate
```

## Recommandations personnalisées

Le moteur utilise K-Means pour regrouper les gares selon leurs profils
touristiques, puis les classe selon les préférences de l'utilisateur :

```python
import pandas as pd

from scripts.research.recommender import (
    RecommendationCriteria,
    TourismRecommender,
)

stations = pd.read_csv("data/station_features.csv")
recommender = TourismRecommender().fit(stations)
recommendations = recommender.recommend(
    RecommendationCriteria(
        patrimoine=0.8,
        nature=0.2,
        events=0,
        attractions=0,
        radius_km=10,
        departure_station_name="Nancy",
        max_distance_km=10,
        exclude_ile_de_france=True,
        favor_poi_with_website=True,
        n_results=5,
    )
)
print(recommendations[
    ["name", "distance_from_departure_km",
     "recommendation_score", "dominant_category"]
])
```

Les préférences sont normalisées automatiquement. Les valeurs doivent être
comprises entre 0 et 1 ; `prefer_popular` contrôle l'importance de la
fréquentation de la gare. `max_distance_km` limite la recherche autour de la
gare de départ. Pour rechercher dans toute la France, renseigner la gare de
départ sans fournir `max_distance_km`. `exclude_ile_de_france=True` retire les
destinations des départements 75, 77, 78, 91, 92, 93, 94 et 95.
Un POI possédant une adresse de site internet compte 3 fois plus qu'un POI sans
site.


## Structure principale

```text
.
├── main.py                         # Point d'entrée
├── poi.py                          # Catégories de points d'intérêt
├── show_map.py                     # Rendu cartographique
├── requirements.txt                # Dépendances Python
├── scripts/
│   ├── data_prep/
│   │   ├── DATA.md                 # Sources et commandes de préparation
│   │   ├── build_stations.py       # Construction des gares
│   │   ├── build_station_transfers.py
│   │   └── pre-traitement-tourism.py
│   ├── itinerary/
│   │   ├── carbon.py               # Calcul des émissions carbone
│   │   ├── itinerary_ui.py         # Interface du trajet
│   │   ├── network.py              # Chargement du réseau SNCF
│   │   ├── planner.py              # Recherche d'itinéraires
│   │   └── route_map.py            # Carte des itinéraires
│   └── research/
│       ├── recommender.py          # Recommandations et clustering
│       └── station_features.py     # Features gare-POI et index spatiaux
└── data/
    ├── raw/                        # Sources téléchargées
    ├── stations.csv                # Liste des gares
    ├── station_features.csv        # Features touristiques des gares
    ├── station_poi_index.csv       # Liens gare-POI
    ├── poi_nearest_station.csv     # Gare la plus proche de chaque POI
    ├── hpoi.csv                   # Points culturels
    ├── npoi.csv                   # Points naturels
    ├── epoi.csv                   # Événements datés
    └── attractions_france.csv      # Attractions
```