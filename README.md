# ORACLE 2.0 — radar de tendances mondiales

ORACLE observe le vocabulaire et les indicateurs structurels de sources multiples, publie un **Billboard Top 20 par domaine**, puis construit un graphe vérifiable **tendance → goulot → fournisseurs de capacités → matières premières → entreprises cotées**.

## État

- Cartographie initiale: **111 sources candidates / 14 domaines** (voir `sources/registry.csv`). Une source CANDIDATE n'est **pas** une connexion vérifiée ni un flux déjà alimenté.
- Sources classées par accès (`OPEN`, `FREE_KEY`, `LIMITED`, `LICENSED`), cadence et rôle.
- **Aucun Top 20, aucune performance et aucun signal d'achat ne sont revendiqués tant que les prélèvements, l'historique et les contrôles ne tournent pas.**
- Les données publiques ne sont pas toutes sous licence libre. Vérifier les conditions d'utilisation de chaque source avant automatisation et redistribution.

## Protocoles

Voir `docs/ORACLE_SPEC_V1.md` pour les quatre moteurs (collecte, Billboard, supply graph, invest), les contrôles de qualité et la validation scientifique.

## Séquence de réalisation

1. Connecter des sources ouvertes de découverte (et mesurer la couverture source/jour/zone/langue).
2. Conserver les observations horodatées et les états d'erreur sans fabriquer de zéro.
3. Démarrer l'historique, comparer à des baselines de même source, de même langue et de même pays.
4. Publier Top 20 par domaine **après** un historique suffisant; classer les données insuffisantes à part.
5. Constituer, avec preuves et degré de confiance, les chaînes bottleneck / picks-and-shovels / commodities.
6. Brancher cours validés et entreprises; backtester *point-in-time*, puis simuler; aucun achat réel automatique.

Un signal vert n'est jamais une garantie de rendement. Le portefeuille ACTUAL, TARGET et la simulation sont strictement distincts.
