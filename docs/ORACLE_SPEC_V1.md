# ORACLE 2.0 — protocole de recherche v1

## Principe

On échantillonne des flux publics et licenciés selon leurs conditions. Un **terme** n'est pas une **tendance**: on détecte des évolutions persistantes du vocabulaire, des associations de termes et des indicateurs fondamentaux. Un échantillon n'est pas « tout Internet ».

## 14 univers

- culture
- social
- news
- technology
- science
- patents
- macroeconomics
- geopolitics
- geography
- demography
- commodities
- supply_chain
- health
- markets

Chaque univers aura un classement autonome Top 20, non un classement global mélangeant des tailles et rythmes d'échantillonnage incomparables.

## 1. Collecte et provenance

Schéma minimal par observation: `source_id`, `url`, `first_seen_at_utc`, `published_at_utc` (si fourni), `collected_at_utc`, `language`, `geo`, `domain`, `source_category`, `licensed_excerpt_or_keywords`, `license_status`, `hash`, `collection_status`. Quand une publication est retirée, respecter sa politique d'effacement.

Conserver volume total de publications observées et taux de défaillance de chaque source, éviter doublons et syndications, séparer les observations des valeurs structurées (PIB, brevets, matières, population). Enregistrer la date de publication initiale et la date effective de disponibilité : on ne peut exploiter que ce qui était connu à la date du signal.

Périmètre stable, représentativité documentée. L'utilisation de Reddit et des flux à accès restreint est désactivée jusqu'à autorisation adéquate. Bloomberg payant est non requis.

## 2. Billboard — Top 20 PAR DOMAINE

- Extraction multilingue de noms, expressions 1–4 mots et cooccurrences. Dédupliquer variantes et synonymes en gardant les termes d'origine et le pays.
- Fréquence normalisée = documents distincts mentionnant le concept / documents éligibles de la même source et du même jour × 10 000.
- Baselines 7/28/90 jours, par source/pays/langue. Indicateurs: volume, accélération, nouveauté, persistance, diversité de sources indépendantes, propagation géographique et robustesse à la suppression de la plus grosse source.
- Ne pas confondre volume de couverture médiatique et intérêt du public. Pour sources lentes (brevets, démographie, PIB) utiliser la période de publication propre, jamais interpoler des observations inexistantes au jour le jour.
- Le score combiné est d'abord un prototype calibré sur séries historiques, puis figé et testé hors échantillon; chaque composante doit être visible.
- Afficher rang du jour, rang J-1, delta, séries 7/30/90 jours, nb de sources, nb de régions, qualité de données, citations de preuves.
- Un rang n'est publié comme « validé » qu'après couverture suffisante et seuils de stabilité fixés avant les tests; sinon « exploratoire / historique insuffisant ».
- Prévoir catégories ACTIVE, STABLE, EMERGING, DECAYING, INSFFICIENT_DATA sans prétendre à une probabilité.

## 3. Graphe de dépendance

Pour chaque tendance, rechercher:
1. **Goulot** : capacité rare mesurable (énergie, réseau, capital, temps de fabrication, compétences, permis, infrastructure). Preuve : capacités, commandes, délais, restrictions.
2. **Pelles & pioches** : fournisseurs de machines, consommables, logiciels, infrastructures, services et contrats, avec identité juridique/LEI et tickers vérifiés.
3. **Matières premières** : composants physiques direct et amont, zones de production, concentration des fournisseurs, substituts et exposition aux prix.

Chaque lien du graphe porte `claim`, `source_url`, `published_at`, `observed_at`, `confidence`, `counterevidence` et `review_status`. Aucune affirmation de chaîne d'approvisionnement sans source. Les sociétés cotées peuvent avoir une exposition économique négligeable malgré un lien thématique.

## 4. Invest — signal indépendant

Le code couleur s'applique **à une entreprise / instrument au moment T**, pas automatiquement à la tendance.

- **VERT**: fenêtre admissible à analyse d'entrée seulement si données récentes et vérifiées, cotation / liquidité / spreads valides, risque financier et valorisation quantifiés, signaux techniques conformes à la règle *préenregistrée*, concentration du portefeuille compatible, qualité de chaîne suffisamment prouvée.
- **ORANGE**: risque ou incertitude intermédiaire mesurés; surveiller, demander validation manquante ou réduire l'exposition proposée. Pas d'ordre automatique.
- **ROUGE**: liquidité insuffisante, données incohérentes ou risque excessif, invalidation de la thèse, dépassement des limites; aucune nouvelle entrée.
- **GRIS / NON ÉVALUABLE**: absence de cours fiables ou d'historique, clé manquante, sources non confirmées. Cela ne doit jamais être transformé en vert ou orange par défaut.

La couleur indique une **évaluation de risque / conditions d'entrée**, et non une probabilité de gain connue. Un prix peut baisser malgré un signal vert. Conserver les preuves complètes et versions de modèle pour chaque signal.

## 5. Validation scientifique

- Backtest *walk-forward* et hors échantillon, univers dynamique incluant sociétés radiées; pas de fuite du futur ni de survivorship bias.
- Séries de prix à dividendes et splits pris en compte; contrôler la devise (CHF), change, coûts, spreads, turnover, impôts et frais réalistes.
- Benchmark QQQ à dates et devises cohérentes (et d'autres comparateurs si la stratégie est globale).
- Comparer rendement annualisé, volatilité, max drawdown, ratio de Sharpe, nombre d'ordres, exposition, turnover, sensibilité aux hypothèses et intervalles de confiance.
- Utiliser vintages de données macro (ALFRED) et dates exactes de publication des brevets/rapports.
- Comparer contre stratégies naïves : momentum, pondération égale, aléatoire, QQQ. Si le modèle n'apporte rien, le déclarer.

## 6. Garde-fous d'exploitation

- Fail closed : erreur source, clé expirée, couverture insuffisante -> pas de recommandation investissable.
- Des tests garantissent la séparation `ACTUAL`, `TARGET`, `PAPER`.
- Conserver coûts et licences par source, journal des runs et version du classement.
- Aucun ordre boursier réel avant consentement explicite et contrôles d'exécution séparés.
