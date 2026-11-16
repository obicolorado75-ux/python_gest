# GestDepot

Application de bureau de gestion commerciale pour un **dépôt de boissons** en Côte
d'Ivoire. Fonctionne **hors ligne**, stocke ses données sur l'ordinateur de
l'entreprise et n'exige aucune connexion Internet pour démarrer, vendre,
consulter ou imprimer.

> Ce dépôt implémente la priorité **P0** du cahier des charges
> [`implementations.md`](implementations.md) : base locale, catalogue,
> conditionnements, stock, achats/réceptions, ventes/caisse, clients, paiements
> et sauvegarde — socle stable avant les fonctions avancées.

## Ce qui fonctionne aujourd'hui (P0)

| Domaine | Contenu |
|---|---|
| Base locale | SQLite dans le répertoire de données utilisateur, clés étrangères actives, journal WAL, migrations Alembic |
| Sécurité | Connexion Argon2id, rôles et permissions vérifiés dans les services, journal d'audit, désactivation sans suppression |
| Catalogue | Produits, catégories, marques, unités, **conditionnements configurables** (ex. 1 casier = 24), listes de tarifs, historique des coûts, import contrôlé |
| Stock | Journal immuable des mouvements, soldes et CMP mobile, alertes de seuil, rapprochement journal/soldes, inventaires avec régularisation tracée |
| Achats | Fournisseurs, commandes d'achat, réceptions partielles ou totales, facture et solde fournisseur, suggestions de réappro |
| Ventes | Écran de saisie rapide, panier multi-conditionnements, remises, ventes à crédit avec plafond, paiements mixtes, retours et annulations tracés |
| Clients | Fiche, plafond de crédit, relevé de compte, règlements partiels (le CA n'est pas recalculé) |
| Caisse | Ouverture, mouvements, dépenses, clôture avec écart conservé ; espèces séparées du Mobile Money |
| Rapports | Tableau de bord, marges, exports **Excel** (openpyxl) et **PDF** (ReportLab), ticket 80 mm |
| Sauvegarde | Copie cohérente via l'API SQLite, contrôle `PRAGMA integrity_check`, empreinte SHA-256, restauration protégée |

## Aperçu

| Écran | Capture |
|---|---|
| Tableau de bord | `docs/captures/dashboard.png` |
| Ventes / Caisse | `docs/captures/sales.png` |
| Produits et catalogue | `docs/captures/products.png` |
| Stocks et mouvements | `docs/captures/stock.png` |
| Clients et crédits | `docs/captures/customers.png` |
| Achats et réapprovisionnement | `docs/captures/purchases.png` |
| Caisse et dépenses | `docs/captures/cash.png` |
| Inventaires | `docs/captures/inventory.png` |
| Marges et rapports | `docs/captures/reports.png` |
| Paramètres et sauvegarde | `docs/captures/settings.png` |

## Prérequis

- Python **3.10+**
- Windows 10/11 ou macOS 12+ (Linux fonctionne aussi pour le développement)

## Installation et lancement

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

python -m gestdepot                 # lance l'interface graphique
```

Au **premier lancement**, un assistant crée le compte administrateur et le nom du
dépôt. Les données sont ensuite écrites dans :

- Windows : `%LOCALAPPDATA%\GestDepot\`
- macOS : `~/Library/Application Support/GestDepot/`
- Linux : `~/.local/share/GestDepot/`

Sous-dossiers créés automatiquement : `database/`, `backups/`, `exports/`,
`documents/`, `logs/`, `attachments/`.

## Base de démonstration

Utilisable hors de la base réelle pour découvrir l'application :

```python
from gestdepot.app import bootstrap_database, seed_demo_data
bootstrap_database()
seed_demo_data()
```

Les produits, clients et fournisseurs créés portent le suffixe « (démo) ».

## Tests

```bash
pytest                    # unitaires + intégration (scénarios T01–T18)
pytest tests/ui           # tests d'interface (Qt en mode offscreen)
```

Les tests utilisent une base isolée par test : aucune donnée réelle n'est touchée.
Les tests d'interface sont ignorés automatiquement si Qt ne peut pas démarrer
(bibliothèques graphiques système absentes, par exemple dans un conteneur).

## Migrations

```bash
alembic upgrade head                       # base utilisateur par défaut
alembic -x url=sqlite:///./dev.db upgrade head   # base de développement
alembic -x url=sqlite:///./dev.db revision --autogenerate -m "message"
```

## Organisation du code

```
src/gestdepot/
├── app.py                 amorçage, données de démonstration, point d'entrée
├── config/                chemins de données utilisateur (§4.4)
├── database/
│   ├── models/            modèles SQLAlchemy (domaine persistant)
│   ├── migrations/        migrations Alembic
│   └── session.py         moteur, transactions, numérotation, amorçage
├── domain/rules.py        calculs indépendants de l'interface (marges, CMP…)
├── services/              règles métier : ventes, stock, caisse, rapports…
├── security/              Argon2id, sessions, permissions, audit
├── reports/               exports Excel et PDF
├── printing/              tickets de caisse imprimables
└── ui/                    fenêtre principale, pages, dialogues, composants
```

L'interface n'exécute **aucune requête SQL** : elle appelle les services, qui
valident les règles et enregistrent les opérations en une seule transaction.

## Documentation

- [`implementations.md`](implementations.md) — cahier des charges de référence
- [`README.md`](README.md) — ce document
- [`DATABASE.md`](DATABASE.md) — schéma, contraintes et migrations
- [`USER_GUIDE.md`](USER_GUIDE.md) — guide utilisateur
- [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md) — administration, sauvegarde, restauration
- [`RELEASE_NOTES.md`](RELEASE_NOTES.md) — historique et suivi des phases
- [`PACKAGING.md`](PACKAGING.md) — construction des installateurs Windows/macOS

## Limites connues de cette étape

- Un seul poste : pas de partage réseau simultané (§2.3).
- Consignes, livraisons et commandes clients : modèle de données prêt, écrans
  partiels (priorité P1).
- Chiffrement applicatif de la base non activé : utiliser BitLocker/FileVault
  (§8.4).
- Les installateurs Windows/macOS doivent être produits **sur** leur plateforme
  respective (§4.1).
