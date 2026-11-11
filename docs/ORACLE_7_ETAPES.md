# ORACLE 2.0 — les 7 étapes validées

**Principe : Internet → évolution du wording → tendances → économie réelle → sociétés cotées → étude de trading.**

## 1. Cartographier les sources
Registry: \`sources/registry.csv\`, 111 sources candidates dans 14 univers. Champs: domaine, licence, API/URL, périodicité et statut. Une source candidate n'est pas un connecteur opérationnel. Respecter les conditions d'utilisation. Bloomberg et licences propriétaires sont des sources non automatiques sans contrat.

## 2. Mesurer les tendances — Billboard TOP 5 PAR SOURCE
Créer une observation par jour et par source; relever le wording dans les documents autorisés. Pour chaque expression, calculer un taux normalisé : documents distincts qui mentionnent l'expression / documents disponibles de *cette même source* × 10 000.

Classement quotidien sur trois fenêtres de 7 jours : R_ancien, R_précédent, R_récent. Vitesse = R_récent - R_précédent. **Accélération = R_récent - 2 × R_précédent + R_ancien** (mentions pour 10 000 documents par semaine au carré). N'admettre que vitesse > 0 ET accélération > 0, au moins 4 mentions dans la fenêtre récente, dans au moins 2 jours différents, avec volume récent >= 35 documents. Le Top 5 reste vide sans **21 jours calendaires consécutifs non vides**, indépendamment de la popularité absolue.

Le ranking demeure exploratoire tant que nous n'avons pas vérifié la détection multilingue, la désyndication, le débruitage, les mots composés et la robustesse aux changements de couverture. Ne jamais interpréter l'absence de données comme une fréquence zéro; les sources à rythme lent se comparent selon leurs vraies périodes et non selon un échantillonnage journalier artificiel. Le statut source doit être conservé : OK / EMPTY / ERROR.

Le tableau source affiche les 5 expressions classées, leur accélération et leur vitesse, volume, jours actifs, preuves URL, date et qualité. Le classement par domaine v0.1 est conservé seulement pour compatibilité, mais n'est plus le produit principal.

## 3. Mapper le marché
Définir le besoin réel, le marché et les segments associés, acheteurs, substitution, zones géographiques et maturité. Estimer les marchés adressables TAM/SAM/SOM avec hypothèses, devises, dates et sources; distinguer discours internet, adoption effective et revenus mesurables.

## 4. Détecter les limites du marché
Tester les goulots: capacité industrielle, temps de production, énergie, réseau, talents, logistique, financement, brevets et contraintes réglementaires. Mesurer au lieu d'affirmer. Séparer contrainte observable, hypothèse et contre-argument.

## 5. Identifier « pelles et pioches »
Cartographier la chaîne de valeur, fournisseurs d'équipements, logiciels, composants, consommables et services. Rechercher matières premières, substitutions, exposition à leur prix, concentration de la production et risques géopolitiques. Chaque relation est un lien documenté et daté.

## 6. Top 10 sociétés par tendance
D'abord vérifier identifiants (ticker, place, LEI, ISIN) et exposition économique réelle, revenus pertinents, concurrents, avantage compétitif, bilan, rentabilité, valorisation et liquidité. Classement transparent avec sources et contre-arguments. Ne pas fabriquer dix noms si les preuves ne permettent pas dix noms. Entreprises radiées et biais de survivance inclus en historique.

## 7. Optimiser l'étude de trading
Test d'hypothèses pré-enregistrées de prix d'entrée/sortie, horizon, momentum, valorisation, volatilité, risques événementiels, coûts, dividendes, change et concentration. Simulation *point-in-time* et walk-forward hors échantillon, après frais. Benchmarks QQQ et indice mondial en devise cohérente.

- **VERT** : tous les critères pré-enregistrés sont vérifiés, fenêtre d'entrée admissible, pas de garantie de résultat.
- **ORANGE** : risques intermédiaires ou incertitude qui imposent surveillance.
- **ROUGE** : risque hors limites ou invalidation.
- **GRIS** : données non disponibles ou invalides → décision bloquée.

Un signal investissable dépend de preuves par entreprise, de prix vérifiés et de règles testées, jamais d'un Top 5 de mots seul.

## Avancement vérifiable
1. Catalogue de sources : réalisé, à auditer source par source.
2. 13 connecteurs gratuits expérimentaux (arXiv, Hacker News, Google Trends RSS, Wikipedia, Federal Register) et Top 5 par source avec seuil d'historique : implémentés, non validés scientifiquement.
3–7. Architecture spécifiée, pas encore de pipeline économique ou trading opérationnel.

Ne jamais confondre prototype fonctionnel et alpha validé.
