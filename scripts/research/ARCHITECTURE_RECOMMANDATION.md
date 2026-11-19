Document généré par IA

# Documentation technique : Moteur de recommandation touristique ferroviaire


Ce document détaille l'architecture, les choix algorithmiques de Machine Learning et les ajustements métier implémentés dans le moteur de recommandation (`TourismRecommender`).

---

## 1. Architecture et fonctionnement global

Le pipeline se décompose en **trois briques principales** :

1. **`RecommendationCriteria` (Le contrat d'entrée)** : Une `dataclass` immuable qui valide et normalise les préférences de l'utilisateur (ex : si l'utilisateur saisit `patrimoine=0.8` et `nature=0.2`, `normalized_preferences()` ramène la somme à `1.0`).
2. **`TourismRecommender` (Le moteur de sélection des gares)** :
   * **`fit()`** : Prépare les données en amont. Il filtre les gares trop peu fréquentées (`min_visitors`), construit un index spatial (`BallTree`) et calcule, pour chaque rayon (ex : 5 km, 10 km), des matrices de scores normalisés.
   * **`recommend()`** : Applique les filtres géographiques (distance maximale depuis la gare de départ, exclusion de l'Île-de-France), calcule un score de recommandation hybride, dédoublonne par ville et renvoie le Top $N$.
3. **`get_top_pois_for_recommendations()` (Le générateur d'itinéraire local)** : Une fois les meilleures gares sélectionnées, cette fonction extrait les 20 meilleurs Points d'Intérêt (POI) autour de chacune d'elles en respectant les proportions demandées par l'utilisateur.

---

## 2. L'algorithme et la logique Machine Learning

Le moteur repose sur une approche hybride combinant **recherche spatiale**, **filtrage basé sur le contenu (*Content-Based Filtering*)** et **scoring heuristique**.

### A. Normalisation par rang percentile (`fit`)

Les volumes de POI varient fortement d'une catégorie à l'autre (il existe beaucoup plus de monuments historiques que de parcs d'attractions). Une normalisation classique *Min-Max* écraserait les valeurs à cause des grandes métropoles (Paris, Lyon).

* **Solution ML** : Le code utilise `.rank(pct=True)` pour transformer les volumes bruts en **percentiles compris entre 0 et 1**. Une gare au percentile `0.90` en nature fait partie des 10 % les mieux dotées de France.
* **Exception du zéro** : `np.where(raw_vals > 0, ranked, 0.0)` garantit qu'une gare ayant `0` POI reste strictement à `0.0` (sans cette condition, `rank(pct=True)` lui attribuerait un rang moyen non nul en raison des égalités).

### B. Indexation spatiale via `BallTree`

Pour calculer les distances entre gares sans recourir à une double boucle coûteuse en $\mathcal{O}(N^2)$, le modèle utilise un **BallTree** avec la métrique de **Haversine** (calcul de distance orthodromique sur une sphère à partir des coordonnées GPS converties en radians).

### C. Similarité Cosinus avec `NearestNeighbors` (KNN)

Le modèle représente l'utilisateur et chaque gare dans un espace vectoriel à 4 dimensions :

$$\vec{v} = (\text{patrimoine}, \text{nature}, \text{events}, \text{attractions})$$

L'algorithme `NearestNeighbors(metric="cosine")` mesure l'angle entre le vecteur de préférences de l'utilisateur $\vec{u}$ et le vecteur de chaque gare $\vec{g}$ :

$$\text{profile\_alignment} = \cos(\theta) = \frac{\vec{u} \cdot \vec{g}}{\|\vec{u}\| \|\vec{g}\|}$$

* **Pourquoi le cosinus ?** Il mesure l'**orientation** (la proportion relative des catégories) indépendamment de la taille de la ville. Une petite ville avec `[0.2, 0.0, 0.0, 0.0]` obtient un alignement parfait (`1.0`) pour un profil 100 % patrimoine, au même titre qu'une grande ville `[0.9, 0.0, 0.0, 0.0]`.

### D. Moyenne géométrique pour corriger le biais du cosinus

Le cosinus seul présente un biais : une gare avec 1 seul monument (`[0.05, 0, 0, 0]`) obtient un alignement de `1.0` pour une recherche 100 % patrimoine, tout comme une ville en comptant 200 (`[0.98, 0, 0, 0]`).

* **L'intensité** : Le code calcule le produit scalaire $\text{intensity} = \vec{g} \cdot \vec{u}$, qui mesure la **richesse réelle** de l'offre dans les catégories demandées.
* **La fusion** : Le score touristique combine les deux métriques via une moyenne géométrique :

$$\text{tourism\_score} = \sqrt{\text{profile\_alignment} \times \text{intensity}}$$

Cette formule pénalise sévèrement les gares ayant un bon ratio mais quasi aucun POI, tout en récompensant les destinations à la fois spécialisées *et* bien dotées.

### E. Formule du score final de recommandation

Le score final pondère la pertinence touristique, la fréquentation de la gare et (si une gare de départ est renseignée) la distance parcourue :

$$\text{base\_score} = (1 - w_{\text{pop}}) \cdot \text{tourism\_score} + w_{\text{pop}} \cdot \text{popularity\_score}$$

$$\text{recommendation\_score} = (1 - w_{\text{dist}}) \cdot \text{base\_score} + w_{\text{dist}} \cdot \min\left(\frac{d}{d_{\max}}, 1.0\right)$$

*Avec par défaut : $w_{\text{pop}} = 0.20$ et $w_{\text{dist}} = 0.15$.*

---

## 3. Les ajustements métier et correctifs intégrés

Ce code intègre plusieurs ajustements fins destinés à corriger des biais réels observés sur les données touristiques :

1. **Traitement asymétrique des sites web (`favor_poi_with_website`)**
   * *Problème* : Valoriser les POI ayant un site web (`_website_weighted_count`) permet de filtrer le bruit (petites plaques commémoratives sans intérêt) au profit des vrais sites touristiques. En revanche, les **événements** (`epoi`) sont ponctuels et disposent rarement d'un site web dédié.
   * *Ajustement* : Dans `_get_col_name()` et dans le calcul d'`attractivity_score`, la pondération par site web est **désactivée pour les événements** (`prefix != "epoi"`) afin de ne pas les invisibiliser.

2. **Dédoublonnage urbain (`_deduplicate_by_city`)**
   * *Problème* : Sans dédoublonnage, un Top 5 autour de Nancy ou Lyon renverrait plusieurs gares de la même agglomération (*Lyon Part-Dieu*, *Lyon Perrache*, *Lyon Jean Macé*, etc.).
   * *Ajustement* : Le code regroupe les résultats par commune/code INSEE (ou à défaut dans un rayon de 5 km via un second `BallTree`) et ne conserve que la gare au score le plus élevé par ville.

3. **Bonus d'éloignement (`DISTANCE_WEIGHT = 0.15`)**
   * *Problème* : Lorsqu'un utilisateur cherche une escapade jusqu'à 100 km, recommander la gare de banlieue située à 3 km manque d'intérêt.
   * *Ajustement* : Le score final intègre un léger bonus proportionnel à la distance (`distance_from_departure_km / max_dist`), incitant à l'évasion dans la limite du rayon fixé, tout en excluant la gare de départ elle-même.

4. **Répartition par quotas avec « méthode du plus fort reste » (`get_top_pois_for_recommendations`)**
   * *Problème* : Si un utilisateur demande 60 % de nature et 40 % de patrimoine sur 20 POI, un simple tri global risquerait d'afficher 18 POI nature (car plus nombreux) et 2 patrimoine.
   * *Ajustement* : La fonction calcule des quotas entiers exacts (`12` nature, `8` patrimoine), gère les arrondis via les plus forts restes décimaux, et ne comble avec une autre catégorie que si la catégorie demandée est épuisée autour de la gare.

5. **Filtrage temporel strict des événements (`event_date`)**
   * Si une date de voyage est fournie, les événements sont filtrés sur l'intervalle `[Date début, Date fin]` (avec repli sur `Date début` si la date de fin est manquante), tandis que les lieux permanents (musées, parcs) restent conservés.