# Tourisme Train SNCF

Projet d'exploitation de données ferroviaires et touristiques en France.

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
fichiers sources et reconstruire les données, consulter
[`scripts/data_prep/DATA.md`](scripts/data_prep/DATA.md), puis exécuter les
commandes indiquées depuis la racine du projet.

En particulier, ce document explique comment :

- télécharger les données des gares et de leur fréquentation ;
- générer [`data/stations.csv`](data/stations.csv) avec `build_stations.py` ;
- télécharger les données touristiques ;
- générer les fichiers de points d'intérêt (`attractions_france.csv`,
  `hpoi.csv`, `npoi.csv` et `epoi.csv`) avec
  `pre-traitement-tourism.py`.

Les colonnes d'identifiants doivent être lues comme du texte afin de conserver
les zéros initiaux des codes INSEE et UIC.

## Lancer le programme

Avec l'environnement virtuel activé :

```bash
python main.py
```

Pour quitter l'environnement virtuel :

```bash
deactivate
```

Pour calculer les distances entre les gares et les POI avec `BallTree` :

```bash
python scripts/research/station_features.py
```

Le fichier [`data/station_features.csv`](data/station_features.csv) contient les
compteurs de POI à moins de 20, 15, 10, 5, 3 et 1 km, ainsi que la distance du
POI le plus proche, pour chaque gare.

Pour récupérer la liste des POI proches d'une gare :

```python
from station_features import find_nearby_pois, load_pois, load_stations

nearby = find_nearby_pois(
    load_stations(),
    load_pois(),
    station_name="Paris Austerlitz",
    radius_km=3,
)
print(nearby[["distance_km", "Nom", "category"]])
```

Pour éviter de reconstruire l'index spatial à chaque recherche :

```bash
python scripts/research/build_proximity_indexes.py
```

Cette commande crée `data/station_poi_index.csv`, qui contient les liens
gare-POI jusqu'à 20 km, et `data/poi_nearest_station.csv`, qui contient la
gare la plus proche de chaque POI. La recherche peut ensuite utiliser
`find_nearby_pois_from_index`. Exemple :

```python
from station_features import find_nearby_pois_from_index, load_pois, load_stations
import pandas as pd

nearby = find_nearby_pois_from_index(
    load_stations(),
    load_pois(),
    pd.read_csv("data/station_poi_index.csv"),
    station_name="Paris Austerlitz",
    radius_km=1,
)
print(nearby[["distance_km", "Nom", "category"]])
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
        culture=0.8,
        nature=0.2,
        events=0,
        attractions=0,
        radius_km=10,
        departure_station_name="Nancy",
        max_distance_km=10,
        exclude_ile_de_france=True,
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

## Structure principale

```text
.
├── main.py                         # Point d'entrée
├── best_poi.py                      # Traitement des points d'intérêt
├── station_features.py              # Calcul des features gare-POI
├── scripts/
│   └── research/
│       ├── build_proximity_indexes.py       # Construction des index spatiaux
│       ├── recommender.py                   # Recommandations et clustering
│       └── station_features.py              # Calcul des features gare-POI
├── requirements.txt                # Dépendances Python
├── data/                            # Données préparées
└── scripts/data_prep/DATA.md       # Téléchargement et préparation des données
```