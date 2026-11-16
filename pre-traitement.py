import pandas as pd

NAME_FILE_ATTRACTIONS = "data/raw/parcs-du-monde.csv"
NAME_FILE_TOURISME = "data/raw/datatourisme.csv"

def pre_traitement_attractions() -> pd.DataFrame:
    # Correspondance entre les colonnes sources et les noms cibles
    correspondance_colonnes = {
        "nom_fr": "Nom",
        "wikidata": "Identifiant",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "site_officiel": "Site internet",
    }
    colonnes_finales = ["Nom", "Identifiant", "Latitude", "Longitude", "Site internet"]

    # Charger les données depuis le fichier CSV
    df = pd.read_csv(NAME_FILE_ATTRACTIONS)

    # Supprimer les lignes où le pays n'est pas la France et où une année de fermeture est renseignée
    # (Retirez la condition sur "pays" si cette colonne n'existe plus dans votre CSV)
    masque = df["annee_fermeture"].astype("string").fillna("").str.strip().eq("")
    if "pays" in df.columns:
        masque = masque & df["pays"].astype("string").fillna("").str.strip().eq("FR")

    # Filtrer, renommer et réordonner les colonnes en une seule opération
    df_final = (
        df.loc[masque, list(correspondance_colonnes.keys())]
        .rename(columns=correspondance_colonnes)
        [colonnes_finales]
        .reset_index(drop=True)
    )

    # Enregistrer le DataFrame nettoyé dans un nouveau fichier CSV
    df_final.to_csv("data/attractions_france.csv", index=False)

    return df_final



def obtenir_types_uniques(sep: str = ",", separateur_valeurs: str = ",") -> list[str]:
    """
    Extrait la liste triée des valeurs uniques des colonnes 'Sous-type' d'un fichier DATAtourisme.
    """
    df = pd.read_csv(
        NAME_FILE_TOURISME,
        sep=sep,
        usecols=[3, 4],
        dtype="string",
    )
    
    # Empile les deux colonnes en une seule série, nettoie et dédoublonne
    sous_types_uniques = (
        df.stack()
        .dropna()
        .str.split(separateur_valeurs) # Gère les cellules contenant plusieurs valeurs
        .explode()
        .str.strip()
        .unique()
    )
    
    return sorted(st for st in sous_types_uniques if st)
   
HIGH_VALUE_POI = [
    "Musée",
    "Château et demeure de prestige",
    "Site archéologique",
    "Site culturel",
    "Site religieux",
    "Lieu de mémoire",
    "Patrimoine industriel",
    "Galerie d'art",
    "Opéra",
    "Théatre",
    "Vivarium - Aquarium",
    "Zoo - parc animalier",
    "Parc naturel",
    "Grotte",
    "Cascade",
    "Canyon",
    "Cirque naturel",
    "Volcan",
    "Téléphérique touristique",
    "Train touristique",
    "Office de tourisme",
    "Maison du tourisme"
]

NATURE_POI = [
    "Lac",
    "Forêt",
    "Montagne",
    "Vallée",
    "Plage",
    "Dune",
    "Marais",
    "Zone humide",
    "Curiosité naturelle",
    "Point de vue",
    "Source",
    "Rivière ou fleuve",
    "Parc et jardin",
    "Itinéraire pédestre",
    "Itinéraire cyclable",
    "Randonnée",
    "Via ferrata",
    "Vélorail"
]

EVENTS = [
    "Festival",
    "Concert",
    "Exposition",
    "Spectacle",
    "Son et lumière",
    "Carnaval",
    "Fête traditionnelle",
    "Évènement culturel",
    "Pièce de théâtre"
]


import pandas as pd

def filtrer_par_sous_types(
    sous_types_recherches: list[str],
    nom_sortie: str,
    sep: str = ",",
    separateur_valeurs: str = ",",
) -> pd.DataFrame:
    """
    Extrait Nom, Identifiant, Latitude, Longitude et Site internet pour les lignes
    dont au moins un sous-type figure dans la liste fournie.
    """
    colonnes_finales = ["Nom", "Identifiant", "Latitude", "Longitude", "Site internet"]
    
    # Index : 0=Nom, 1=Identifiant, 3=Sous-type, 4=Sous-type, 10=Latitude, 11=Longitude, 12=Site internet
    df = pd.read_csv(
        NAME_FILE_TOURISME,
        sep=sep,
        usecols=[0, 1, 3, 4, 10, 11, 12],
        dtype="string",
    )

    cibles = {st.strip() for st in sous_types_recherches}
    cols_sous_type = [df.columns[2], df.columns[3]]  # Les colonnes aux index 3 et 4 du CSV

    # Empile, découpe et nettoie toutes les valeurs des deux colonnes Sous-type en gardant l'index de ligne
    sous_types_exploses = (
        df[cols_sous_type]
        .stack()
        .dropna()
        .str.split(separateur_valeurs)
        .explode()
        .str.strip()
    )

    # Récupère les index uniques des lignes qui contiennent au moins un sous-type recherché
    index_valides = (
        sous_types_exploses[sous_types_exploses.isin(cibles)]
        .index.get_level_values(0)
        .unique()
    )

    masque = df.index.isin(index_valides)
    df = df.loc[masque, colonnes_finales].reset_index(drop=True)
    df.to_csv(nom_sortie, index=False)
    return df


if __name__ == "__main__":
    pre_traitement_attractions()
    types = obtenir_types_uniques()
    print(types)
    filtrer_par_sous_types(HIGH_VALUE_POI, "data/hpoi.csv")
    filtrer_par_sous_types(NATURE_POI, "data/npoi.csv")
    filtrer_par_sous_types(EVENTS, "data/epoi.csv")
