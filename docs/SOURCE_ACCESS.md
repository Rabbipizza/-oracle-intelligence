# ORACLE 2.0 — adaptation aux contraintes de chaque source

## Concept

Une source est un instrument de mesure indépendant. On ne doit jamais fusionner ou rebaptiser silencieusement des données de secours. Le Top 5 mesure la variation **dans la même source et avec le même périmètre**. Toute rupture de couverture exige recalibration.

## Cycle de vie

| Classe d'accès | Stratégie |
|---|---|
| OPEN | Lire une API / un RSS public dans les limites du fournisseur. L'absence de clé ne prouve pas un droit de redistribution. |
| FREE_KEY | Désactiver tant que l'environnement ne contient pas la clé désignée ; ne jamais enregistrer la clé dans Git. |
| LIMITED | Demander une validation des droits et du quota avant activation. Respecter le volume d'appels et les conditions d'exploitation. |
| LICENSED | Désactivé tant qu'une licence effective n'est pas confirmée ; chercher des **sources indépendantes** publiques du même secteur, jamais les substituer à l'identité Bloomberg. |
| MANUAL | Accès manuel / étude de sources, pas de collecte automatique. |

Une erreur HTTP 429 devient RATE_LIMITED, 401 AUTH_REQUIRED, 403 FORBIDDEN ; 5xx TEMPORARY_ERROR, mauvaise structure FORMAT_ERROR. Pas de retry agressif : protéger les quotas. Aucune observation synthétique lors d'une erreur.

## Stratégie par source active

Configurée dans \`sources/access_profiles.json\`. Chaque source possède : accès, format, période de publication, mode d'échantillonnage, nombre maximum de documents, budget de requêtes, timeout et limite de charge. Une source non enregistrée est bloquée par défaut. Les clés d'API sont lues exclusivement dans des secrets d'environnement.

19 connecteurs expérimentaux, dont Google Trends RSS, arXiv, Wikipedia, Hacker News, Google News, fédéral, EUR-Lex et MIT. Le statut de la collecte est publié dans \`data/latest.json -> source_health\`.

Le catalogue \`sources/registry.csv\` répertorie 111 sources **candidates** et leurs accès : ni \`rights_verification\` ni \`connector_verification\` ne sont confirmées par simple inclusion dans le CSV.

## Adaptation aux fréquences de publication

- Réseaux / RSS : échantillonnage quotidien, limites de taille et de requêtes individualisées.
- Sources irrégulières : une lecture réussie sans nouvelle publication vaut **EMPTY**, pas une panne. Un jour en erreur 429/403 ne peut être considéré comme un vrai zéro.
- Brevets / statistiques / démographie : leurs véritables séries hebdomadaires, mensuelles et annuelles seront suivies avec des *publication timestamps* ; aucune interpolation quotidienne fictive.
- Flux TOP_LIST (Google Trends, Hacker News, pageviews): ce sont des **échantillons de listes populaires**, pas une mesure exhaustive du volume de mentions sur Internet. Afficher cette limitation sur le cockpit.
- Sources financières : identité de l'instrument, licence et ajustements historiques obligatoires avant tout signal.

## Fallbacks publics envisageables (NON substitués automatiquement)

- Bloomberg inaccessible → SEC EDGAR, banques centrales, FRED et registres publics, chacun conservant son propre identifiant et son champ de mesure.
- Reddit restreint → Hacker News, Bluesky et Stack Exchange, en tant que capteurs distincts et non « données Reddit ».
- API Google Trends indisponible → RSS des recherches populaires, source de type TOP_LIST distincte des volumes de recherche historiques.

## Contrôles à poursuivre

- Couverture par langue/pays et séries stables (éviter biais de quotas et changement de taille des échantillons).
- Conditions et droits par jeu de données avant exploitation et diffusion.
- Suivi des budgets réels et Retry-After de chaque fournisseur, au besoin backoff persistant entre runs.
- Éligibilité de la source au Billboard selon mode de mesure et historique, et qualité d'une éventuelle stratégie de repli.
