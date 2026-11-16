# ADMIN_GUIDE.md — administration, sauvegarde et restauration

## 1. Utilisateurs, rôles et permissions

Menu **Paramètres et sauvegarde → Utilisateurs**. Les rôles livrés sont :

| Rôle | Permissions principales |
|---|---|
| Administrateur | tout, y compris utilisateurs, paramètres, sauvegardes, audit |
| Gérant | ventes, achats, stocks, clients, fournisseurs, caisse, inventaires, rapports |
| Caissier | création de ventes, encaissements, ouverture/clôture de sa caisse |
| Magasinier | réceptions, mouvements de stock, inventaires, catalogue |
| Livreur | livraisons qui lui sont affectées |

Bonnes pratiques :

- **Un compte par personne** : l'audit identifie l'auteur de chaque opération.
- **Désactiver, ne pas supprimer** : un utilisateur désactivé conserve son
  historique ; son compte ne peut plus se connecter.
- **Code PIN** : réservé au poste de caisse pour un déverrouillage rapide.
- Les permissions sont vérifiées dans la couche métier, pas seulement dans
  l'interface : masquer un bouton ne suffit pas à protéger une opération.

## 2. Paramètres du dépôt

Menu **Paramètres et sauvegarde → Dépôt** : nom, téléphone, adresse et pied de
page des documents. Ces informations apparaissent sur les tickets et les rapports
PDF. La devise est le FCFA (XOF), sans décimale.

## 3. Sauvegardes

### Ce que fait l'application

- sauvegarde **quotidienne automatique** au démarrage si la dernière date d'un
  jour précédent ;
- sauvegarde **à la fermeture propre** ;
- sauvegarde **manuelle** depuis l'écran Sauvegarde ;
- copie via l'API SQLite (`Connection.backup`) : le journal WAL est inclus, aucun
  fichier n'est copié « à chaud » ;
- `PRAGMA integrity_check` sur la copie, taille et empreinte **SHA-256**
  enregistrées dans l'historique ;
- rétention configurable (`BackupService.purge_old`, 7 par défaut).

### Limite importante (hors ligne)

Une tâche planifiée ne peut pas s'exécuter lorsque l'ordinateur est éteint ou que
l'application est fermée. La sauvegarde quotidienne a donc lieu au premier
démarrage suivant. Pour une protection réelle :

1. choisissez un **dossier de sauvegarde sur un disque externe** (option de
   destination dans le service de sauvegarde) ;
2. activez le chiffrement du disque : **BitLocker** (Windows) ou **FileVault**
   (macOS) — SQLite n'est pas chiffré par défaut ;
3. conservez au moins une copie sur un support physiquement distinct.

### Bonnes pratiques

- Vérifiez l'indicateur « Dernière sauvegarde » dans la barre supérieure.
- Copiez régulièrement le dossier `backups/` sur une clé USB.
- Désinstaller l'application ne supprime ni la base ni les sauvegardes ; la
  suppression des données doit être un choix explicite.

## 4. Restauration

Menu **Paramètres et sauvegarde → Sauvegarde → Restaurer une sauvegarde**.
La procédure est volontairement stricte :

1. permission `restore.run` requise (administrateur) ;
2. la sauvegarde choisie est **vérifiée** (intégrité + tables) ;
3. une **sauvegarde de sécurité** de la base actuelle est créée avant écrasement ;
4. les connexions sont fermées, puis la base est remplacée ;
5. l'application est réinitialisée ; **redémarrez-la** pour repartir sur la base
   restaurée.

Une sauvegarde invalide est refusée : aucune base valide n'est jamais écrasée par
un fichier douteux.

### Procédure avant mise à jour

1. Sauvegarde manuelle + copie sur support externe.
2. Notez la version de l'application.
3. Installez la nouvelle version et lancez-la : les migrations en attente sont
   appliquées automatiquement au démarrage (une base ancienne est reconnue et
   rattachée à la version courante). `alembic upgrade head` reste disponible pour
   une intervention manuelle.
4. Vérifiez le catalogue, un stock et une vente de test.

### Procédure après incident

1. N'écrivez plus dans la base.
2. Sauvegardez le fichier `gestdepot.db` endommagé pour analyse.
3. Restaurez la dernière sauvegarde valide (procédure ci-dessus).
4. Contrôlez les rapprochements : stocks, soldes clients, caisse, consignes.

## 5. Journal d'audit

Menu **Paramètres et sauvegarde → Journal d'audit** (permission `audit.view`).
Sont journalisés : connexions et échecs, créations et modifications du catalogue,
changements de prix et de coûts, remises exceptionnelles, ventes, annulations,
retours, paiements, ouvertures et clôtures de caisse, dépenses, inventaires,
sauvegardes et restaurations.

Chaque entrée conserve l'acteur, l'action, l'objet, l'ancienne et la nouvelle
valeur, le commentaire et l'horodatage.

## 6. Maintenance

```bash
alembic check                      # détecte une divergence modèles/migrations
python -m pytest                   # suite de tests (base isolée)
```

- Contrôlez régulièrement le rapprochement stock/journal (menu Stocks →
  **Vérifier les soldes**) et les écarts de clôture de caisse.
- Les écarts ne sont jamais corrigés automatiquement : utilisez un inventaire ou
  une opération tracée.
- En cas de doute sur la santé de la base :
  `sqlite3 gestdepot.db "PRAGMA integrity_check;"`.
