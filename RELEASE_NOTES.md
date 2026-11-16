# RELEASE_NOTES.md — historique et suivi des phases

## Suivi des phases (`implementations.md` §11)

| Phase | État | Contenu livré |
|---|---|---|
| 0 — Cadrage et prototype | ✅ fait | dépôt, base locale, fenêtre principale, lancement hors ligne, tests |
| 1 — Fondations et catalogue | ✅ fait (P0) | architecture en couches, migrations, connexion, utilisateurs/rôles, paramètres, catégories, marques, unités, conditionnements, produits, tarifs, import contrôlé |
| 2 — Stocks, achats | ✅ P0 livré | journal immuable, soldes, CMP, fournisseurs, commandes (remise + frais d'approche), réceptions avec refus, paiements fournisseurs, inventaires, consignes et emballages |
| 3 — Caisse et ventes | ✅ P0 livré | POS, panier, tarifs, remises, paiements mixtes, crédit, retours, annulations, ventes suspendues (F8), ticket |
| 4 — Clients, livraisons, finances | 🟡 partiel | clients, crédits, relevés, paiements affectés, sessions de caisse, dépenses ; livraisons et commandes clients à faire (P1) |
| 5 — Inventaires, analyses, rapports | 🟡 P0 livré | inventaires guidés, tableau de bord, marges, exports Excel/PDF ; rapports spécialisés à compléter |
| 6 — Sécurité, sauvegarde | 🟡 partiel | audit, permissions, sauvegarde/restauration vérifiées ; permissions fines par action et tests de régression à étendre |
| 7 — Packaging | ⬜ à faire | scripts de construction fournis, installateurs à produire sur Windows/macOS |

## v0.1.3 — caisse et dépenses complètes (16 novembre 2026)

### Ajouté

- **Mouvements manuels de caisse** : retrait, apport et correction autorisée
  (motif obligatoire), avec refus explicite de tout motif métier saisi à la main
  (`encaissement_vente`, `depense`… proviennent des services concernés).
- **Correction d'une session clôturée** (`correct_closed_session`) : mouvement
  horodaté rattaché à la session (`corrects_session_id`, `corrected_at`,
  `correction_reason`), recalcul du comptage et de l'écart, ancienne valeur
  conservée dans l'audit ; onglet **Corrections** (migration `2053a78bdf38`).
- **Dépenses** : date de la dépense (futur refusé), référence de justificatif,
  catégorie obligatoire, **annulation motivée** par contre-mouvement
  (`cancel_expense`) — la dépense reste consultable avec le statut « Annulée » et
  sort des totaux ; répartition `expenses_by_category`.
- **Catégories de dépenses** : écran de gestion, suppression refusée si la
  catégorie est utilisée.
- **Barre d'actions des écrans** : retour à la ligne automatique au-delà de
  4 boutons (plus de libellé tronqué, §5.1).

### Corrigé

- L'écran caisse débordait à droite avec sept actions sur une seule ligne.

## v0.1.2 — achats et consignes complets (16 novembre 2026)

### Ajouté

- **Commandes d'achat** : remise négociée et frais d'approche (transport,
  autres frais) répartis au prorata des lignes ; le coût « landed » est figé sur
  chaque ligne et utilisé lors de la réception, donc intégré au CMP.
- **Réceptions** : quantités reçues, quantités **refusées** et coût constaté
  modifiable, commentaire de réception (table `purchase_orders`,
  `purchase_order_lines`, migration `c25937c56bfc`).
- **Paiements fournisseurs** (`StockService.pay_supplier`) : solde dû réduit,
  rattachement optionnel à une facture, mouvement de caisse par moyen ;
  permission `suppliers.pay`.
- **Historique des achats** : commandes (y compris soldées/annulées), paiements,
  factures avec reste dû ; annulation motivée et **réouverture auditée** d'une
  commande soldée (`cancel_order`, `reopen_order`).
- **Écran Consignes et emballages** (§5.8, jusque-là absent) : types
  d'emballages, mouvements client/fournisseur (remis, retourné, reçu, rendu,
  cassé, ajusté), comptes de consigne en quantité et en valeur, remboursement de
  consigne tracé en caisse (`deposits.manage`), solde dû au fournisseur par type.
- Moyens de paiement déplacés dans la couche domaine (`domain.rules.PAYMENT_METHODS`)
  pour être partagés par les ventes, la caisse, les achats et les consignes.

### Corrigé

- **Mise à niveau des bases existantes** : le schéma n'était créé qu'au premier
  démarrage (`create_all`) et les migrations Alembic n'étaient jamais appliquées,
  si bien qu'une base d'une version antérieure provoquait une erreur
  (`no such column`) et bloquait l'application. `init_engine` applique désormais
  `upgrade_database` : base neuve → `stamp` de la tête, base existante → `upgrade`,
  base antérieure à Alembic → adoption puis tête. Test de non-régression ajouté
  (0,2 s au premier démarrage, aucune action ensuite).
- Une commande d'achat nouvellement créée expose correctement ses lignes
  (objets détachés après commit).

## v0.1.1 — caisse complète (16 novembre 2026)

### Ajouté

- **Paiement mixte** : une vente peut être réglée par plusieurs moyens
  (espèces, Mobile Money, virement…). Chaque encaissement reçoit son numéro
  `PAY-…`, son mouvement de caisse et une ligne dans `sale_payments` ; le total
  des encaissements est contrôlé côté service et plafonné au dû côté écran
  (table `sale_payments`, migration `92b311107557`).
- **Ventes suspendues (F8)** : suspendre conserve le panier en JSON sans aucune
  écriture de stock, de caisse ou de créance ; dialogue **Ventes suspendues**
  pour reprendre (le panier revient en caisse) ou abandonner (abandon tracé dans
  l'audit). Table `held_sales`.
- **Modifier la quantité** d'une ligne du panier, ou la retirer, sans ressaisie.
- **Retours et annulations depuis l'écran de vente** : bouton *Historique /
  retours*, quantités retournables bornées (`SalesService.returnable_lines`),
  motifs obligatoires, traçabilité conservée.

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
- **Tests** : 146 tests (scénarios T01–T18, paiements mixtes, ventes suspendues,
  retours, achats/consignes, migrations et mise à niveau automatique, atomicité,
  schéma, exports, tickets, interface).

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
- Chiffrement applicatif de la base non activé (§8.4).
- Installateurs Windows/macOS à construire sur leurs plateformes respectives.
