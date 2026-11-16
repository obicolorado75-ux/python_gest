# RELEASE_NOTES.md — historique et suivi des phases

## Suivi des phases (`implementations.md` §11)

| Phase | État | Contenu livré |
|---|---|---|
| 0 — Cadrage et prototype | ✅ fait | dépôt, base locale, fenêtre principale, lancement hors ligne, tests |
| 1 — Fondations et catalogue | ✅ fait (P0) | architecture en couches, migrations, connexion, utilisateurs/rôles, paramètres, catégories, marques, unités, conditionnements, produits, tarifs, import contrôlé |
| 2 — Stocks, achats | 🟡 P0 livré | journal immuable, soldes, CMP, fournisseurs, commandes, réceptions, inventaires ; consignes : service + écran partiel |
| 3 — Caisse et ventes | 🟡 P0 livré | POS, panier, tarifs, remises, paiements, crédit, retours, ticket ; ventes suspendues non livrées |
| 4 — Clients, livraisons, finances | 🟡 partiel | clients, crédits, relevés, paiements affectés, sessions de caisse, dépenses ; livraisons et commandes clients à faire (P1) |
| 5 — Inventaires, analyses, rapports | 🟡 P0 livré | inventaires guidés, tableau de bord, marges, exports Excel/PDF ; rapports spécialisés à compléter |
| 6 — Sécurité, sauvegarde | 🟡 partiel | audit, permissions, sauvegarde/restauration vérifiées ; permissions fines par action et tests de régression à étendre |
| 7 — Packaging | ⬜ à faire | scripts de construction fournis, installateurs à produire sur Windows/macOS |

## v0.1.0 — socle P0 (16 novembre 2026)

### Ajouté

- **Base locale** : SQLite dans le répertoire utilisateur, clés étrangères
  actives, journal WAL, amorçage idempotent, migrations Alembic (50 tables).
- **Sécurité** : Argon2id, rôles/permissions vérifiés côté services, limitation
  des tentatives, journal d'audit, désactivation sans suppression.
- **Catalogue** : produits, catégories, marques, unités, conditionnements
  configurables, listes de tarifs, historique des coûts, import avec
  prévisualisation et détection des doublons.
- **Stock** : journal immuable, soldes avec CMP mobile, alertes de seuil,
  rapprochement journal/soldes, inventaires avec régularisation tracée.
- **Achats** : fournisseurs, commandes d'achat, réceptions totales/partielles,
  factures et soldes fournisseurs, suggestions de réapprovisionnement.
- **Ventes** : écran de saisie rapide avec raccourcis, multi-conditionnements,
  remises contrôlées, ventes à crédit avec plafond, paiements mixtes, retours et
  annulations tracés, ticket 80 mm imprimable.
- **Caisse** : sessions, mouvements, dépenses, clôture avec écart conservé ;
  espèces séparées des paiements Mobile Money.
- **Rapports** : tableau de bord, marges, exports Excel et PDF.
- **Sauvegarde** : copie cohérente via l'API SQLite, contrôle d'intégrité,
  empreinte SHA-256, restauration protégée par authentification et vérification.
- **Tests** : 75 tests (scénarios T01–T18, atomicité, schéma, exports, tickets,
  interface).

### Corrigé pendant cette étape

- services non importables (appels `auth.log` non fermés) — corrigés ;
- isolation des tests : une base neuve par test, plus de fuite entre scénarios ;
- calcul du total de ligne pour un conditionnement (prix casier + reliquat) ;
- remboursement espèces plafonné à ce qui a été réellement encaissé ;
- coût des marchandises vendues corrigé des retours dans la marge ;
- prix au conditionnement : plus de repli silencieux vers le prix unitaire ;
- cartes du tableau de bord dupliquées à chaque rafraîchissement ;
- relations ORM détachées (utilisateur, client) provoquant des erreurs d'affichage ;
- colonnes manquantes dans les rapports et statuts techniques affichés en anglais.

### Limites connues

- Un seul poste, pas de partage réseau (§2.3).
- Livraisons, commandes clients et bons de livraison : à implémenter (P1).
- Ventes suspendues/reprises, paiements mixtes multi-lignes : à compléter.
- Chiffrement applicatif de la base non activé (§8.4).
- Installateurs Windows/macOS à construire sur leurs plateformes respectives.
