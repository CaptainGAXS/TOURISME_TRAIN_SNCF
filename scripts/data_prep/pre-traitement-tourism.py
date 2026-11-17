import pandas as pd
from poi import HIGH_VALUE_POI, NATURE_POI, EVENTS

NAME_FILE_ATTRACTIONS = "data/raw/parcs-du-monde.csv"
NAME_FILE_TOURISME = "data/raw/datatourisme.csv"
MIN_LATITUDE = 41.0
MAX_LATITUDE = 51.2
MIN_LONGITUDE = -5.5
MAX_LONGITUDE = 10.0


def nettoyer_poi(df: pd.DataFrame) -> pd.DataFrame:
    """Conserve les POI géolocalisés en France métropolitaine et dédoublonne."""
    df = df.copy()
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Latitude", "Longitude"])
    df = df[
        df["Latitude"].between(MIN_LATITUDE, MAX_LATITUDE)
        & df["Longitude"].between(MIN_LONGITUDE, MAX_LONGITUDE)
    ].copy()

    df["Identifiant"] = df["Identifiant"].astype("string").str.strip()
    df["Nom"] = df["Nom"].astype("string").str.strip()
    df = df.drop_duplicates()

    identifiant = df["Identifiant"].fillna("")
    doublon_identifiant = identifiant.ne("") & identifiant.duplicated(keep="first")
    cle_coordonnees = (
        df["Latitude"].round(6).astype("string")
        + "|"
        + df["Longitude"].round(6).astype("string")
    )
    cle_nom = (
        df["Nom"]
        .fillna("")
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )
    doublon_nom_coordonnees = (cle_coordonnees + "|" + cle_nom).duplicated(
        keep="first"
    )
    df = df.loc[~(doublon_identifiant | doublon_nom_coordonnees)]
    return df.reset_index(drop=True)

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
    df_final = nettoyer_poi(df_final)

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
    df = nettoyer_poi(df.loc[masque, colonnes_finales].reset_index(drop=True))
    df.to_csv(nom_sortie, index=False)
    return df


if __name__ == "__main__":
    pre_traitement_attractions()
    types = obtenir_types_uniques()
    print(types)
    filtrer_par_sous_types(HIGH_VALUE_POI, "data/hpoi.csv")
    filtrer_par_sous_types(NATURE_POI, "data/npoi.csv")
    filtrer_par_sous_types(EVENTS, "data/epoi.csv")
