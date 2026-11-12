# ORACLE 2.0 — radar de tendances mondiales

ORACLE observe le vocabulaire et les indicateurs structurels de sources multiples, publie un **Billboard Top 20 par thème**, puis construit un graphe vérifiable **tendance → goulot → fournisseurs de capacités → matières premières → entreprises cotées**.

## État

- Cartographie initiale: **111 sources candidates / 14 domaines** (voir `sources/registry.csv`). Une source CANDIDATE n'est **pas** une connexion vérifiée ni un flux déjà alimenté.
- Sources classées par accès (`OPEN`, `FREE_KEY`, `LIMITED`, `LICENSED`), cadence et rôle.
- **Les Top 5 ne sont calculés qu'après 21 jours consécutifs de données par source ; aucun signal d'achat n'est encore autorisé.**
- Les données publiques ne sont pas toutes sous licence libre. Vérifier les conditions d'utilisation de chaque source avant automatisation et redistribution.

## Protocoles

Voir `docs/ORACLE_SPEC_V1.md` pour les quatre moteurs (collecte, Billboard, supply graph, invest), les contrôles de qualité et la validation scientifique.

## Séquence de réalisation

1. Connecter des sources ouvertes de découverte (et mesurer la couverture source/jour/zone/langue).
2. Conserver les observations horodatées et les états d'erreur sans fabriquer de zéro.
3. Démarrer l'historique, comparer à des baselines de même source, de même langue et de même pays.
4. Publier Top 5 par source **après 21 jours consécutifs de mesures** ; classer les données insuffisantes à part.
5. Constituer, avec preuves et degré de confiance, les chaînes bottleneck / picks-and-shovels / commodities.
6. Brancher cours validés et entreprises; backtester *point-in-time*, puis simuler; aucun achat réel automatique.

Un signal vert n'est jamais une garantie de rendement. Le portefeuille ACTUAL, TARGET et la simulation sont strictement distincts.

## Nouvelle feuille de route (7 étapes)

[Lire le cahier des charges](docs/ORACLE_7_ETAPES.md). Top 5 par source selon accélération du wording, puis marché, goulots, fournisseurs, Top 10 sociétés et trading validé. Dashboard : [`index.html`](index.html).

## Connecteurs complémentaires et chaîne de recherche

Des flux RSS publics (Google News, NASA Earth Observatory, Réserve fédérale et EUR-Lex) sont ajoutés à titre expérimental. Leur fonctionnement n'est confirmé qu'après un run réussi : une URL connue ne garantit pas un flux disponible, ni une licence de redistribution.

`oracle_pipeline.py` produit une file de dossiers pour les tendances confirmées par le Billboard, puis bloque les étapes marché / fournisseurs / trading lorsqu'il manque des preuves vérifiées. Aucun classement d'entreprises ni trading automatique n'en découle actuellement.

## Politiques d'accès adaptées

Chaque source active a un profil explicite (accès, période, quota d'articles, budget de requêtes, limites HTTP) dans [`sources/access_profiles.json`](sources/access_profiles.json). Les sources inaccessibles sont signalées sans injecter de faux zéros et les sources non configurées sont bloquées. Voir [`docs/SOURCE_ACCESS.md`](docs/SOURCE_ACCESS.md).

## Billboard hebdomadaire style charts

Le cockpit affiche désormais des **thèmes** (dont Geek & Gaming), et non les noms des sources. Chaque thème possède un Top 20 fondé sur un score de fréquence normalisé à l'intérieur de chaque source. Avant deux périodes de sept jours comparables, les positions sont marquées **PROVISOIRES** et les mouvements hebdomadaires sont **indisponibles**, jamais inventés. Les preuves restent reliées à chaque entrée.

En l'absence d'un historique de 14 jours avec des sources comparables, la liste du jour n'est pas encore un classement d'accélération. Les catégories et filtres lexicaux v0.1 sont heuristiques : une validation multilingue et sémantique est nécessaire avant un usage scientifique.
