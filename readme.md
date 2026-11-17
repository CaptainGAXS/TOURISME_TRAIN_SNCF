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

## Structure principale

```text
.
├── main.py                         # Point d'entrée
├── best_poi.py                      # Traitement des points d'intérêt
├── requirements.txt                # Dépendances Python
├── data/                            # Données préparées
└── scripts/data_prep/DATA.md       # Téléchargement et préparation des données
```