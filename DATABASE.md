# DATABASE.md — schéma, contraintes et migrations

Base : **SQLite** locale, fichier unique dans le répertoire de données utilisateur
(`~/.local/share/GestDepot/database/gestdepot.db` sur Linux,
`%LOCALAPPDATA%\GestDepot\database\` sur Windows,
`~/Library/Application Support/GestDepot/database/` sur macOS).

## Principes

| Règle | Mise en œuvre |
|---|---|
| Montants en entiers XOF | colonnes `Integer`, jamais de flottants |
| Quantités | entiers, toujours en **unités de base** du produit |
| Clés étrangères | `PRAGMA foreign_keys=ON` à chaque connexion |
| Journal fiable | `stock_movements` immuable ; `stock_balances` rapprochable |
| Traçabilité | aucune suppression d'opération : annulation, retour ou régularisation |
| Transactions | une vente = un seul commit (vente, lignes, stock, caisse, créance, consigne) |
| Numérotation | `document_sequences` incrémenté dans la transaction (`VTE-2026-000001`) |
| Archivage | référentiels marqués `archived`/`active`, jamais supprimés |

## Tables principales

### Configuration et sécurité
`roles`, `permissions`, `role_permissions`, `users`, `audit_logs`,
`company_settings`, `app_settings`.

- `users.password_hash` : Argon2id, jamais en clair.
- `users.active` : désactivation logique ; l'historique reste consultable.
- `audit_logs` conserve acteur, action, objet, ancienne/nouvelle valeur et date.

### Catalogue
`categories`, `brands`, `units`, `products`, `product_barcodes`,
`product_packagings`, `price_lists`, `product_prices`, `product_cost_history`.

- `product_packagings.factor` : nombre d'unités de base (1 casier = 24).
- `product_prices` : couple unique (produit, liste, conditionnement) ;
  `packaging_id NULL` désigne le prix à l'unité de base.
- `product_cost_history` : historique des coûts d'achat (marges historiques).

### Stock
`stock_movements`, `stock_balances`, `inventory_sessions`, `inventory_lines`,
`product_batches`.

- `inventory_sessions.status` : `draft`, `counting`, `reviewed`, `validated`,
  `cancelled` ; `validated_at` / `validated_by` figent la validation.
- `inventory_sessions.threshold_value` : seuil d'écart de valeur exigeant un
  contrôle ; `inventory_lines.reviewed` / `review_comment` / `counted_at`
  conservent le comptage et son contrôle.

- `stock_movements.quantity` est **signée** ; motifs autorisés :
  `mouvement_initial`, `reception`, `sortie_vente`, `retour_client`,
  `retour_fournisseur`, `casse`, `perte`, `peremption`, `correction_inventaire`.
- `stock_balances.quantity` = somme du journal (contrôle `StockService.reconcile`).
- `stock_balances.weighted_avg_cost` = CMP mobile mis à jour à chaque entrée.

### Ventes et clients
`customers`, `customer_orders`, `customer_order_lines`, `sales`, `sale_lines`,
`sale_returns`, `sale_return_lines`, `customer_payments`, `payment_allocations`,
`customer_credit_events`, `sale_payments`, `held_sales`.

- `sale_lines` fige désignation, unité, prix, remise et **coût CMP** au moment de
  la vente : les marges historiques ne sont jamais recalculées.
- `sales.deposit_amount` isole les consignes du chiffre d'affaires.
- `customer_payments.customer_id` est nullable (encaissement au comptoir).
- `sale_payments` porte le détail d'un encaissement mixte : une ligne par moyen
  de paiement, chacune reliée à son `customer_payments` (un numéro `PAY-…` par
  encaissement, donc un mouvement de caisse par moyen).
- `held_sales` conserve le panier d'une vente suspendue en JSON, sans vente, sans
  mouvement de stock ni de caisse : rien n'existe comptablement avant validation.

### Achats et fournisseurs
`suppliers`, `purchase_orders`, `purchase_order_lines`, `goods_receipts`,
`goods_receipt_lines`, `supplier_invoices`, `supplier_payments`.

- Une commande ne touche jamais le stock ; seule une réception validée l'augmente.
- `purchase_order_lines.received_qty` porte le reliquat des réceptions partielles.
- `purchase_orders.discount_amount`, `freight_fees`, `other_fees` : remise et
  frais d'approche ; `purchase_order_lines.landed_cost` fige le coût réel
  (convenu × coefficient de répartition) utilisé pour le CMP.
- `goods_receipt_lines.quantity_refused` conserve les quantités refusées à la
  réception.
- `supplier_payments` (avec `comment`) et `supplier_invoices.paid_amount`
  déterminent le solde dû, mis à jour par `StockService.pay_supplier`.

### Consignes, livraisons, caisse
`returnable_packaging`, `deposit_movements`, `deliveries`, `delivery_lines`,
`cash_sessions`, `cash_movements`, `expense_categories`, `expenses`.

- `deposit_movements.quantity` signée ; le solde client = somme des mouvements.
- `cash_movements` distingue espèces (`especes`) et moyens non espèces ;
  seules les espèces entrent dans le solde théorique de caisse.
- `cash_sessions` conserve `theoretical_amount`, `counted_amount`, `difference`.
- `cash_movements.corrects_session_id` (avec `corrected_at`, `correction_reason`)
  identifie une correction rattachée à une session clôturée : l'écart est
  recalculé, l'ancien reste dans `audit_logs`.
- `expenses.cancelled_at` / `cancel_reason` : annulation logique d'une dépense,
  qui sort des totaux sans être supprimée.

### Sauvegardes et documents
`backup_history`, `document_sequences`, `generated_documents`.

## Index

Index sur les références et codes uniques (`products.reference`,
`products.barcode`, `customers.code`, `suppliers.code`), sur les dates
(`sales.at`, `stock_movements.at`, `cash_movements.at`, `deposit_movements.at`)
et sur les clés étrangères de jointure (`*_id`, `status`, `reason`).

## Migrations Alembic

```bash
alembic upgrade head                              # base utilisateur
alembic -x url=sqlite:///./dev.db upgrade head    # base de développement
alembic -x url=sqlite:///./dev.db revision --autogenerate -m "message"
alembic -x url=sqlite:///./dev.db check           # vérifie l'absence de divergence
```

- La révision initiale `ff962e37ee63` crée l'ensemble du schéma.
- `92b311107557` ajoute `sale_payments` et `held_sales` (paiements mixtes et
  ventes suspendues).
- `c25937c56bfc` ajoute remise/frais d'approche sur les commandes, le coût
  « landed » des lignes et le commentaire des paiements fournisseurs.
- `2053a78bdf38` ajoute les corrections de caisse et l'annulation de dépenses.
- `75b49f9d7032` ajoute le contrôle des écarts d'inventaire et la traçabilité
  de validation.
- `render_as_batch=True` : les modifications de colonnes sont possibles sur SQLite.
- Au démarrage, l'application crée la base si besoin puis **applique les
  migrations en attente** (`init_engine` → `upgrade_database`) : une nouvelle
  version met à niveau une base existante sans manipulation. Une base créée
  avant l'introduction d'Alembic est reconnue et rattachée à la révision de tête
  (`stamp`) sans perte de données. Faites une sauvegarde avant toute mise à jour
  (§8) ; `alembic upgrade head` reste disponible pour une intervention manuelle.

## Sauvegarde et intégrité

Voir `ADMIN_GUIDE.md`. En résumé : copie via l'API SQLite (`Connection.backup`,
WAL inclus), `PRAGMA integrity_check` obligatoire, empreinte SHA-256 enregistrée
dans `backup_history`, restauration refusée si la copie est invalide.

## Rapprochements fournis

- Stock courant ↔ somme de `stock_movements` (`StockService.reconcile`).
- Solde client ↔ ventes − paiements − retours (`SalesService.customer_statement`).
- Solde caisse théorique ↔ `cash_movements` espèces (`CashService.theoretical_amount`).
- Consignes dues ↔ `deposit_movements` (`DepositService.customer_balance`).

Aucun écart n'est corrigé silencieusement : la correction passe par un inventaire
ou une opération tracée.
