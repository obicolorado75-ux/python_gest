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
| 6 — Sécurité, sauvegarde | ✅ P0 livré | audit, permissions vérifiées dans la couche métier, sauvegarde/restauration vérifiées avec politique (dossier, rétention) et écran dédié |
| 7 — Packaging | ⬜ à faire | scripts de construction fournis, installateurs à produire sur Windows/macOS |

## v0.1.5 — politique de sauvegarde pilotable (16 novembre 2026)

### Ajouté

- **Réglages de sauvegarde persistés** (`app_settings`) : dossier de
  destination (disque externe possible), rétention **quotidienne** et
  **hebdomadaire**, sauvegarde à la fermeture activable/désactivable
  (`BackupService.settings / save_settings`).
- **Rétention** : `purge_old` conserve les N sauvegardes récentes **et** une
  archive par semaine au-delà de cette fenêtre (tri par date de fichier, plus
  de purge liée au nom des fichiers).
- **Écran Paramètres** : dossier avec sélecteur, rétention, case de sauvegarde à
  la fermeture, bouton « Vérifier une sauvegarde », empreinte SHA-256 dans
  l'historique, rappel de la dernière sauvegarde réussie et mention explicite de
  la limite hors ligne (§8.1).
- **Restauration** : la sauvegarde de sécurité créée avant restauration est
  réenregistrée dans l'historique de la base restaurée — l'opérateur retrouve
  toujours de quoi revenir en arrière.

### Ajouté (moyens de paiement configurables, §5.12)

- Nouveau module `services/payment_methods.py` : liste effective des moyens de
  paiement résolue depuis `app_settings` (clé `payments.methods`), libellés
  personnalisés (`code|libellé`), « Espèces » obligatoire, audit
  `payment_methods_update`.
- **Tous** les points de saisie utilisent la configuration courante : caisse
  (vente, paiements mixtes, dépenses, mouvements), clients, consignes et achats.
- Nouvel onglet **Moyens de paiement** dans les paramètres : cases à cocher,
  ajout d'un opérateur libre, enregistrement. Décocher un moyen ne supprime
  aucune donnée historique (il n'est simplement plus proposé).
- La validation métier (`sales`, `cash`, `deposits`, `purchases`) refuse un
  moyen inconnu ou désactivé.

### Ajouté (connexion §5.3)

- Écran de connexion : logo du dépôt (onglet Dépôt), nom, identifiant, champ
  « mot de passe / PIN » avec bascule automatique pour les profils de caisse
  disposant d'un PIN, mention hors ligne, message neutre.
- Limitation progressive aussi appliquée au **PIN** (5 essais → 1 minute), et
  les échecs de connexion sont désormais réellement écrits dans le journal
  d'audit (la transaction était auparavant annulée par l'exception).
- Paramètres → logo du dépôt modifiable (parcourir + affichage).

### Ajouté (restauration §8.3)

- **Ressaisie du mot de passe administrateur** exigée dans le service de
  restauration (`restore(path, password=…)`) : une session laissée ouverte ne
  suffit plus. Trois tests couvrent mot de passe absent, incorrect et rôle sans
  permission.

### Corrigé

- Après une restauration, la base restaurée ne connaissait pas la copie de
  sécurité prise juste avant l'opération.

## v0.1.4 — inventaires contrôlés (16 novembre 2026)

### Ajouté

- **Inventaire ciblé ou global** : sélection des produits à compter, seuil de
  contrôle des écarts paramétrable par session (migration `75b49f9d7032`).
- **Comptage horodaté** (`counted_at`), statuts `draft → counting → reviewed →
  validated` et `cancelled`.
- **Contrôle des écarts importants** (§5.13 étape 6) : `check_control` liste les
  lignes dont l'écart de valeur dépasse le seuil ; `review_gap` enregistre le
  constat (commentaire obligatoire, audit `inventory_gap_review`) ; la validation
  est refusée tant qu'un écart au-dessus du seuil n'est pas contrôlé. Un nouveau
  comptage annule le contrôle précédent.
- **Abandon motivé** d'un inventaire non validé (`cancel_session`, audit), sans
  effet sur le stock ; un inventaire validé se corrige uniquement par un nouvel
  inventaire (régularisation non destructive).
- **Traçabilité de la validation** : `validated_at`, `validated_by`, écarts et
  coûts conservés sur les lignes.

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
- **Tests** : 217 tests (scénarios T01–T18, paiements mixtes, ventes suspendues,
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
