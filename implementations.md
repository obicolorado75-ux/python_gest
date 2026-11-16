GestDepot — Cahier des charges fonctionnel et technique
Version : 1.0
Date : 16 novembre 2026
Statut : Spécification de référence pour le développement
Type de produit : Application de bureau de gestion commerciale pour un dépôt de boissons
Nom provisoire : GestDepot

1. Vision et objectifs du projet
   GestDepot est une application de bureau destinée à digitaliser la gestion quotidienne d'un dépôt de boissons en Côte d'Ivoire. Elle doit couvrir le cycle complet de l'activité : catalogue, achats, réception, stockage, ventes, caisse, clients, crédits, livraisons, fournisseurs, consignes, inventaires, dépenses et analyse de la rentabilité.

L'application doit être utilisable sans connexion Internet, conserver les données sur l'ordinateur de l'entreprise et permettre leur sauvegarde, leur restauration et leur exportation vers Excel et PDF.
1.1 Objectifs opérationnels

1. Connaître à tout moment les quantités réellement disponibles.
2. Enregistrer rapidement une vente au comptoir, au détail ou en gros.
3. Suivre les casiers, bouteilles et autres emballages consignés.
4. Gérer les clients débiteurs, les paiements partiels et les livraisons.
5. Contrôler les achats, les réceptions, les fournisseurs et leurs soldes.
6. Distinguer le chiffre d'affaires, les encaissements, les créances, les dépenses et le résultat estimatif.
7. Calculer les coûts, les marges et la rentabilité par produit et par période.
8. Préparer les réapprovisionnements à partir des seuils et de l'historique des ventes.
9. Produire des documents et rapports fiables.
10. Protéger les données contre les erreurs, suppressions accidentelles et pertes matérielles.
    1.2 Principes non négociables

- Une seule entreprise / un seul dépôt dans le périmètre initial. Il ne s'agit pas d'un SaaS multi-entreprise.
- Hors ligne par conception. Aucune connexion Internet ne doit être requise pour démarrer, vendre, consulter les données ou générer les rapports.
- Données locales. La base de données est conservée dans le répertoire de données de l'utilisateur du système, jamais uniquement dans le dossier d'installation.
- Traçabilité. Une opération validée ne doit pas être effacée silencieusement. Une correction doit produire une opération d'annulation ou de régularisation traçable.
- Cohérence transactionnelle. Une vente confirmée, son paiement et sa sortie de stock doivent être enregistrés de manière atomique.
- Personnalisation par l'interface. Les produits, catégories, unités, conditionnements, tarifs, moyens de paiement et seuils doivent être configurables sans modifier le code.
- Montants exacts. Les montants monétaires sont stockés en nombres entiers de FCFA (XOF), jamais en nombres flottants.

2. Périmètre fonctionnel
   2.1 Inclus dans la première version

- Tableau de bord et alertes locales.
- Paramètres du dépôt et gestion des utilisateurs.
- Catalogue de produits, catégories, marques, unités et conditionnements.
- Tarifs de détail, de gros et tarifs par type de client.
- Gestion des stocks et journal des mouvements.
- Casiers, bouteilles et emballages consignés.
- Fournisseurs, commandes d'achat, réceptions et factures fournisseurs.
- Clients, commandes, ventes, paiements, crédits et remboursements.
- Caisse, ouverture, mouvements et clôture.
- Livraisons et bons de livraison.
- Dépenses et suivi des dettes.
- Inventaires physiques et corrections d'écarts.
- Calcul des coûts, marges et résultats estimatifs.
- Rapports et exports Excel/PDF.
- Sauvegarde, restauration et contrôle d'intégrité.
- Journal d'audit.
- Génération d'installateurs Windows et macOS.
  2.2 Hors périmètre initial
  Ces éléments pourront faire l'objet d'une version ultérieure, mais ne doivent pas retarder le socle hors ligne :
- Synchronisation cloud ou entre plusieurs dépôts.
- Application mobile ou portail web client.
- Paiement Mobile Money automatisé via API.
- Envoi automatique de SMS, WhatsApp ou e-mails.
- Comptabilité générale certifiée ou déclaration fiscale automatisée.
- Gestion multi-société ou multi-entrepôt complexe.
- Connexion obligatoire à un serveur distant.
  Les paiements Orange Money, MTN Mobile Money, Moov Money et Wave pourront être enregistrés manuellement comme moyens de paiement. Leur vérification automatique nécessiterait une intégration externe et une connexion.
  2.3 Hypothèse d'utilisation initiale
  La première version fonctionne sur un ordinateur principal dans le dépôt. Plusieurs profils peuvent utiliser successivement l'application sur cet ordinateur. Le partage simultané des données entre plusieurs ordinateurs n'est pas inclus. Une future architecture réseau locale devra être étudiée séparément si plusieurs postes doivent travailler en même temps.

3. Utilisateurs, rôles et permissions
   L'application doit proposer une gestion locale des utilisateurs.
   Rôle Permissions par défaut
   Administrateur Tous les modules, paramètres, utilisateurs, sauvegardes, corrections et rapports
   Gérant Ventes, achats, stocks, clients, fournisseurs, caisse, inventaires et rapports ; paramètres sensibles limités
   Caissier Création de ventes, encaissements, tickets, consultation limitée des clients et clôture de sa caisse
   Magasinier Réceptions, mouvements de stock autorisés, inventaires et consultation du catalogue
   Livreur (optionnel) Consultation des livraisons qui lui sont affectées et mise à jour de leur statut

Exigences de sécurité utilisateur

- Connexion par identifiant et mot de passe ; code PIN rapide facultatif pour un poste de caisse.
- Mots de passe stockés sous forme de hachage sécurisé (Argon2id recommandé), jamais en clair.
- Permissions vérifiées dans la couche métier, et pas uniquement en masquant des boutons.
- Réauthentification ou validation du responsable pour les opérations sensibles.
- Journalisation des connexions, échecs, modifications de prix, remises exceptionnelles, annulations et ajustements.
- Désactivation d'un utilisateur plutôt que suppression de son historique.

4. Architecture technique cible
   4.1 Technologies
   Couche Technologie recommandée Rôle
   Langage Python 3, version stable compatible avec les dépendances Logique de l'application
   Interface graphique PySide6 / Qt 6 Interface bureau moderne
   Base locale SQLite Persistance hors ligne
   Accès aux données SQLAlchemy 2.x Modèles et requêtes structurées
   Migrations Alembic Évolution contrôlée du schéma
   Export Excel openpyxl Classeurs formatés
   Export PDF ReportLab Rapports et documents imprimables
   Graphiques Qt Charts ou PyQtGraph Visualisations du tableau de bord
   Tests pytest Tests unitaires et intégration
   Packaging pyside6-deploy/Nuitka ou PyInstaller après validation Construction des applications
   Windows Installateur EXE ou MSI Distribution Windows
   macOS Application .app distribuée dans un .dmg Distribution macOS

Le choix final du mécanisme de packaging doit être confirmé par un prototype technique. Les versions Windows et macOS doivent être construites et testées sur leurs plateformes respectives. La génération d'un paquet macOS fiable doit être réalisée sur macOS.
4.2 Organisation logicielle
Architecture en couches, afin de séparer l'interface, les règles métier et le stockage :

1. Présentation (UI) : fenêtres, écrans, composants, formulaires, tableaux et dialogues.
2. Services métier : ventes, paiements, stock, achats, consignes, caisse, rapports.
3. Domaine : entités et règles de calcul indépendantes de l'interface.
4. Persistance : modèles SQLAlchemy, requêtes, transactions et migrations.
5. Infrastructure : impression, sauvegardes, fichiers, exports, journaux et configuration.
   L'interface ne doit pas exécuter directement des requêtes SQL complexes. Elle appelle des services métier qui valident les règles et enregistrent les opérations.
   4.3 Arborescence de projet proposée
   gestdepot/
   ├── README.md
   ├── IMPLEMENTATIONS.md
   ├── pyproject.toml
   ├── requirements.txt
   ├── src/
   │ └── gestdepot/
   │ ├── main.py
   │ ├── app.py
   │ ├── config/
   │ ├── database/
   │ │ ├── models/
   │ │ ├── repositories/
   │ │ ├── migrations/
   │ │ └── session.py
   │ ├── domain/
   │ ├── services/
   │ │ ├── sales_service.py
   │ │ ├── stock_service.py
   │ │ ├── purchase_service.py
   │ │ ├── customer_service.py
   │ │ ├── supplier_service.py
   │ │ ├── deposit_service.py
   │ │ ├── cash_service.py
   │ │ ├── delivery_service.py
   │ │ ├── reporting_service.py
   │ │ └── backup_service.py
   │ ├── ui/
   │ │ ├── main_window.py
   │ │ ├── pages/
   │ │ ├── dialogs/
   │ │ ├── widgets/
   │ │ └── styles/
   │ ├── reports/
   │ ├── printing/
   │ ├── security/
   │ └── utils/
   ├── tests/
   │ ├── unit/
   │ ├── integration/
   │ └── ui/
   ├── resources/
   │ ├── icons/
   │ ├── images/
   │ └── templates/
   ├── packaging/
   │ ├── windows/
   │ └── macos/
   └── scripts/
   4.4 Stockage des fichiers utilisateur
   Les données doivent être dans le répertoire utilisateur prévu par le système :

- Windows : dossier de données locales de l'utilisateur, par exemple %LOCALAPPDATA%/GestDepot/.
- macOS : ~/Library/Application Support/GestDepot/.
  Sous-dossiers recommandés : database/, backups/, exports/, documents/, logs/ et attachments/.

La désinstallation de l'application ne doit pas supprimer automatiquement la base ni les sauvegardes. L'utilisateur doit pouvoir choisir explicitement de supprimer les données. 5. Spécifications de l'interface graphique
5.1 Principes ergonomiques

- Interface intégralement en français.
- Devise affichée en FCFA (XOF), avec séparateurs de milliers lisibles.
- Navigation latérale permanente avec icône et libellé.
- Barre supérieure avec recherche, état de sauvegarde, utilisateur connecté et date.
- Écrans lisibles, sans surcharge d'informations.
- Tableaux avec recherche, tri, filtres, pagination si nécessaire et export.
- Formulaires avec libellés explicites, validations immédiates et messages compréhensibles.
- Confirmation pour les opérations irréversibles ou sensibles.
- Raccourcis clavier cohérents et navigation au clavier complète.
- Mise en page adaptée aux résolutions d'écran courantes de Windows et macOS.
- Couleurs d'état cohérentes : succès, attention, erreur et information, sans reposer uniquement sur la couleur.
  5.2 Navigation principale

1. Tableau de bord
2. Ventes / Caisse
3. Commandes clients
4. Produits et catalogue
5. Stocks et mouvements
6. Consignes et emballages
7. Clients et crédits
8. Livraisons
9. Fournisseurs
10. Achats et réapprovisionnement
11. Caisse et dépenses
12. Inventaires
13. Marges et rentabilité
14. Rapports et exports
15. Utilisateurs et paramètres
16. Sauvegarde et restauration
    5.3 Écran de connexion
    Éléments : logo, nom du dépôt, identifiant, mot de passe/PIN selon le profil, bouton de connexion et indication du mode hors ligne.

Comportements : message neutre en cas d'identifiants incorrects, limitation progressive des tentatives, possibilité de verrouillage de session et journalisation des accès.
5.4 Tableau de bord
Filtres : aujourd'hui, hier, 7 derniers jours, mois en cours, période personnalisée.

Indicateurs :

- Chiffre d'affaires net des retours, hors consignes.
- Encaissements réellement reçus par mode de paiement.
- Créances clients ouvertes.
- Dettes fournisseurs ouvertes.
- Dépenses de la période.
- Marge brute estimée.
- Résultat estimatif de gestion.
- Valeur du stock au coût moyen pondéré.
- Produits sous seuil et produits en rupture.
- Commandes à préparer, livraisons en attente et crédits échus.
  Graphiques : ventes par jour, ventes par catégorie, produits les plus vendus, produits les plus rentables et répartition des moyens de paiement.

Règle : chaque indicateur doit pouvoir ouvrir le détail qui le compose. Les chiffres doivent être calculés à partir des opérations sources, et non être saisis manuellement.
5.5 Écran Ventes / Caisse
Écran prioritaire, optimisé pour la saisie rapide.

Zones :

- Recherche produit par nom, référence ou code-barres.
- Liste de produits favoris ou catégories rapides.
- Panier avec désignation, conditionnement, quantité, prix unitaire, remise et total de ligne.
- Pavé numérique intégré ou prise en charge du pavé numérique physique.
- Sélection du client et de son tarif.
- Récapitulatif HT/taxes si activées, consigne, remise et total à payer.
- Paiement : espèces, Mobile Money enregistré manuellement, virement, autre moyen configurable, paiement mixte ou crédit autorisé.
  Actions : ajouter, modifier quantité, retirer une ligne, suspendre une vente, reprendre une vente, appliquer une remise autorisée, valider, imprimer, générer un reçu et ouvrir une nouvelle vente.

Règles :

- Vérifier le stock disponible avant validation.
- Interdire une quantité négative ou nulle.
- Bloquer le dépassement de crédit si une limite est configurée, sauf autorisation.
- Enregistrer le prix, la désignation, l'unité, le coût et la remise au moment de la vente afin de préserver l'historique.
- La validation doit créer la vente, ses lignes, les mouvements de stock, les mouvements de caisse/paiement, le solde client et les mouvements de consigne dans une seule transaction cohérente.
- Une vente confirmée ne peut pas être supprimée directement ; elle est annulée ou remboursée par une opération traçable.
  Raccourcis proposés : F2 rechercher, F4 choisir client, F6 paiement, F8 suspendre, F9 valider, Échap fermer le dialogue. Ils doivent rester personnalisables et ne pas entrer en conflit avec les raccourcis du système.
  5.6 Catalogue produits
  Liste : référence, nom, catégorie, marque, conditionnement, stock disponible, prix d'achat courant, prix détail, prix gros, seuil minimum, statut actif.

Fiche produit :

- Référence interne unique.
- Nom et description facultative.
- Catégorie et marque.
- Code-barres facultatif.
- Unité de stock de base.
- Conditionnements de vente et facteurs de conversion.
- Prix d'achat courant et historique des coûts.
- Prix de vente par tarif.
- Seuil minimum et stock de sécurité.
- Fournisseur principal facultatif.
- Suivi de lot et date de péremption si activé.
- Paramètres de consigne associés.
- Statut actif/archivé.
  Actions : créer, modifier, dupliquer, archiver, importer depuis Excel/CSV, exporter le catalogue et imprimer des étiquettes si une imprimante compatible est installée.

Protection : un produit déjà utilisé dans des opérations ne doit pas être supprimé physiquement ; il doit être archivé.
5.7 Stocks et mouvements
Vue stock : stock physique, quantité réservée (si les commandes réservent le stock), quantité disponible, unité, valeur au coût, seuil, statut.

Types de mouvements : réception d'achat, sortie de vente, retour client, retour fournisseur, casse, perte, péremption, transfert interne futur, correction d'inventaire et mouvement initial.

Chaque mouvement comporte : date, produit, quantité signée, unité de base, motif, document source, coût unitaire si pertinent, utilisateur et commentaire.

La quantité courante doit être calculée ou maintenue par le service de stock à partir d'un journal fiable. Toute mise à jour de stock doit être accompagnée de son mouvement dans la même transaction.
5.8 Consignes et emballages
Ce module gère séparément les marchandises et les emballages réutilisables.

Types configurables : casier, bouteille, fût, bonbonne, palette ou autre emballage.

Fiche d'emballage : code, libellé, capacité éventuelle, consigne unitaire, fournisseur et statut.

Opérations :

- Emballages remis à un client.
- Emballages retournés par un client.
- Emballages reçus d'un fournisseur.
- Emballages rendus au fournisseur.
- Emballages cassés, perdus ou non récupérables.
- Encaissement ou remboursement de consigne.
  Comptes de consigne : soldes par client et par fournisseur, en quantité et en valeur.

Règles :

- La consigne est distincte du chiffre d'affaires produit.
- Le montant facturé pour une consigne doit être suivi comme montant remboursable/dû, selon le traitement comptable retenu par l'entreprise.
- Un retour d'emballage doit diminuer la quantité due et déclencher le remboursement ou l'avoir choisi.
- Les emballages ne doivent pas être confondus avec le stock de boissons pleines.
- Les retours partiels sont autorisés.
  5.9 Clients et crédits
  Liste : code, nom, téléphone, type, plafond de crédit, solde dû, dernière opération et statut.

Fiche : coordonnées, adresse, catégorie/tarif, plafond, historique des ventes, commandes, livraisons, paiements, retours, consignes et relevé de compte.

Fonctions : créer, modifier, archiver, rechercher, consulter le relevé, enregistrer un paiement, appliquer un avoir autorisé et exporter un relevé.

Règles :

- Une vente à crédit crée une créance égale au montant dû.
- Un paiement partiel réduit la créance sans modifier le montant historique de la vente.
- Un paiement ne peut être affecté que dans la limite du solde restant, sauf gestion explicite d'un trop-perçu.
- Les paiements doivent pouvoir être affectés à une ou plusieurs factures.
- Les dates d'échéance et retards doivent être visibles.
  5.10 Commandes clients et livraisons
  Commande client : numéro, client, date, lignes produits, tarifs appliqués, consignes estimées, adresse, date souhaitée, statut et notes.

Statuts : brouillon, confirmée, en préparation, prête, partiellement livrée, livrée, annulée.

Livraison : commande liée, chauffeur, véhicule facultatif, adresse, date prévue, frais, statut, quantités préparées, quantités effectivement livrées, preuve/commentaire et paiement éventuel.

Documents : bon de commande, bon de préparation, bon de livraison, reçu.

Règles :

- La commande en brouillon ne modifie pas le stock.
- Le choix de réservation du stock doit être configurable ; si activé, la quantité réservée ne peut pas être vendue une deuxième fois.
- Une sortie de stock est générée au moment défini par le processus (validation de vente ou confirmation de livraison) et ne doit jamais être comptée deux fois.
- Une livraison partielle laisse un reliquat clair.
- Un échec de livraison ne doit pas effacer la commande ni les paiements déjà reçus.
  5.11 Fournisseurs, achats et réapprovisionnement
  Fiche fournisseur : code, raison sociale, contact, téléphone, adresse, conditions, délai habituel, références fournies, historique des achats, paiements et solde dû.

Commande d'achat : fournisseur, date, lignes, quantités, prix convenus, remise, frais éventuels, date prévue et statut.

Réception : réception complète ou partielle, quantités commandées/reçues/refusées, coût constaté, lot et péremption si suivis.

Règles :

- Une commande d'achat seule n'augmente pas le stock.
- Seule une réception validée augmente le stock.
- Une réception partielle conserve le reliquat de commande.
- La facture fournisseur et les paiements déterminent le solde dû.
- Les prix d'achat doivent conserver leur historique.
- Les frais d'approche peuvent être affectés au coût des articles selon une méthode configurable.
  Suggestion de réapprovisionnement :
- Déclenchement si le stock disponible atteint le seuil.
- Proposition basée sur le stock de sécurité, les ventes moyennes et le délai d'approvisionnement lorsqu'un historique suffisant existe.
- Quantité recommandée = besoin estimé jusqu'au prochain réapprovisionnement + stock de sécurité - stock disponible - commandes déjà attendues.
- La suggestion reste une proposition : le gérant doit la vérifier et la valider.
  5.12 Caisse, paiements et dépenses
  Session de caisse : utilisateur, date/heure d'ouverture, fond initial, mouvements, montant théorique, montant compté, écart, commentaire et clôture.

Mouvements : encaissement d'une vente, règlement d'une créance, remboursement client, paiement fournisseur, dépense, retrait, apport, mouvement de consigne et correction autorisée.

Moyens de paiement configurables : espèces, Orange Money, MTN Mobile Money, Moov Money, Wave, virement bancaire, chèque et autre.

Dépenses : catégorie, bénéficiaire, montant, date, moyen de paiement, justificatif facultatif, commentaire et utilisateur.

Règles :

- Le solde physique de caisse ne comprend que les flux en espèces.
- Les encaissements Mobile Money, virements et autres moyens sont suivis séparément.
- Le chiffre d'affaires d'une vente n'est pas égal à son encaissement si elle est partiellement payée ou à crédit.
- Les règlements de créances ne doivent pas augmenter une seconde fois le chiffre d'affaires.
- Les consignes doivent être identifiées séparément des ventes de boissons.
- La clôture compare le solde théorique au comptage physique et conserve l'écart.
- Une session clôturée ne peut être modifiée que par une procédure d'autorisation et de correction auditée.
  5.13 Inventaires physiques
  Étapes :

1. Créer une session d'inventaire globale ou ciblée.
2. Définir les produits à compter.
3. Afficher le stock théorique au démarrage.
4. Saisir les quantités réellement comptées.
5. Comparer les quantités et valeurs.
6. Faire contrôler les écarts importants.
7. Valider l'inventaire.
8. Générer automatiquement les mouvements de régularisation.
   L'inventaire doit conserver le stock théorique initial, le comptage, l'écart, le coût retenu, l'utilisateur et la date. Les sessions validées sont non destructives et ne peuvent être corrigées que par une nouvelle régularisation.
   5.14 Marges et rentabilité
   Mesures : coût unitaire, prix de vente, marge brute unitaire, taux de marge, taux de marque, marge par ligne, marge par produit, marge par catégorie et marge par période.

Formules de référence :

- Marge brute unitaire = prix de vente HT éventuel - coût unitaire des marchandises.
- Taux de marge = marge brute / coût d'achat × 100.
- Taux de marque = marge brute / prix de vente × 100.
- Marge brute de période = ventes nettes de retours - coût des marchandises vendues.
- Résultat estimatif de gestion = marge brute - dépenses prises en compte.
  Si les taxes sont activées, les calculs doivent distinguer montants HT, taxe et TTC. Les taux et traitements fiscaux ne doivent pas être préremplis comme certitudes : ils doivent être configurés après validation par le responsable et son conseil comptable.

Méthode de coût recommandée pour la V1 : coût moyen pondéré mobile par produit. Chaque vente mémorise le coût appliqué au moment de sa validation. Les rapports historiques ne doivent pas être recalculés avec le prix d'achat courant.

Le résultat affiché doit être nommé résultat estimatif de gestion et non résultat comptable certifié.
5.15 Rapports et exports
Tous les rapports doivent proposer une période et, selon le rapport, des filtres par produit, catégorie, client, fournisseur, utilisateur, statut et moyen de paiement.
Rapport Indicateurs principaux
Ventes Quantités, montants, remises, retours, ventes nettes
Encaissements Montants reçus par date et moyen de paiement
Crédits clients Solde initial, ventes à crédit, paiements, solde final, échéances
Fournisseurs Achats reçus, factures, paiements, solde dû
Stock Quantités, mouvements, ruptures, valorisation
Marges Coût vendu, prix vendu, marge et taux
Dépenses Catégories, montants et modes de règlement
Caisse Fond initial, entrées, sorties, solde théorique, comptage, écart
Consignes Emballages remis, retournés, dus et valeur associée
Livraisons Commandes, statut, montants, frais et reliquats
Inventaires Théorique, compté, écarts et valeur
Activité utilisateurs Actions sensibles et opérations par utilisateur

Excel : feuilles nommées, en-têtes, filtres, formats monétaires, totaux et date de génération.
PDF : logo, coordonnées du dépôt, titre, période, filtres, tableau, totaux, pagination et date de génération.

Les exports sont des copies de consultation ; ils ne doivent jamais modifier les données de la base.
5.16 Paramètres généraux

- Nom du dépôt, logo, coordonnées et pied de page des documents.
- Devise FCFA/XOF.
- Formats de date et de nombre.
- Catalogue, catégories, marques, unités et conditionnements.
- Listes de prix et règles de tarifs.
- Types et valeurs de consignes.
- Seuils d'alerte et niveaux de stock de sécurité.
- Modes de paiement.
- Catégories de dépenses.
- Frais de livraison.
- Taxes éventuelles, après validation.
- Numérotation des documents.
- Imprimantes et formats de tickets.
- Utilisateurs, rôles et permissions.
- Préférences de sauvegarde et rétention.

6. Modèle de données initial
   Le schéma sera relationnel. Les noms ci-dessous sont indicatifs et pourront être affinés pendant l'implémentation, sans supprimer les règles d'intégrité.
   6.1 Configuration et sécurité

- company_settings : identité du dépôt, devise, logo, paramètres généraux.
- users : identifiants, hachage du mot de passe, statut.
- roles : rôles disponibles.
- permissions : permissions élémentaires.
- user_roles et role_permissions : associations.
- audit_logs : acteur, action, objet, date, anciennes/nouvelles valeurs utiles et commentaire.
- app_settings : paramètres techniques et préférences.
  6.2 Catalogue
- categories : catégories de produits.
- brands : marques.
- units : unités de base (bouteille, canette, pièce, litre selon besoin).
- products : références, désignations, catégorie, marque, unité de base, seuils, suivi de lot, état.
- product_barcodes : codes-barres associés.
- product_packagings : conditionnements et facteurs de conversion vers l'unité de base.
- price_lists : détail, gros, revendeur ou liste personnalisée.
- product_prices : prix par produit, liste, période de validité si nécessaire.
- product_cost_history : historique des coûts d'achat.
  6.3 Stock et lots
- stock_movements : journal immuable des entrées/sorties et régularisations.
- stock_balances : soldes courants maintenus et contrôlés par rapport au journal.
- inventory_sessions : sessions d'inventaire.
- inventory_lines : quantités théoriques et comptées.
- product_batches : lots, dates d'entrée et dates de péremption si le suivi est activé.
  6.4 Consignes et emballages
- returnable_packaging : types d'emballages et valeur de consigne.
- deposit_movements : quantité remise, rendue, perdue ou ajustée, partie concernée et document source.
- customer_deposit_balances : vue ou solde calculé par client et type d'emballage.
- supplier_deposit_balances : vue ou solde calculé par fournisseur et type d'emballage.
  6.5 Clients et ventes
- customers : coordonnées, catégorie, tarif, plafond de crédit, statut.
- customer_orders et customer_order_lines : commandes et lignes.
- sales : en-tête de vente, numéro, date, client, statut, totaux figés.
- sale_lines : produit, désignation figée, unité, quantité, prix, remise, coût figé, total.
- sale_returns et sale_return_lines : retours et remboursements.
- customer_payments : paiements reçus.
- payment_allocations : affectation d'un paiement aux ventes/factures.
- customer_credit_events : écritures de compte client si un journal dédié est requis.
  6.6 Fournisseurs et achats
- suppliers : coordonnées et conditions.
- purchase_orders et purchase_order_lines : commandes d'achat.
- goods_receipts et goods_receipt_lines : réceptions totales ou partielles.
- supplier_invoices : factures fournisseurs.
- supplier_payments : règlements fournisseurs.
- supplier_payment_allocations : affectation des paiements aux factures.
  6.7 Livraison et finances
- deliveries et delivery_lines : suivi des livraisons.
- cash_sessions : ouvertures et clôtures.
- cash_movements : entrées et sorties de caisse par moyen de paiement.
- expense_categories : catégories de dépenses.
- expenses : dépenses et justificatifs.
  6.8 Sauvegardes et documents
- backup_history : date, chemin, taille, résultat, empreinte et message d'erreur.
- document_sequences : compteurs de numérotation.
- generated_documents : référence, type et chemin facultatif du document généré.
  6.9 Contraintes techniques
- Clés primaires stables et clés étrangères activées.
- Index sur les références, dates, statuts et clés de recherche utilisées couramment.
- NOT NULL, UNIQUE et contraintes de contrôle pertinentes.
- Dates stockées dans un format ISO cohérent ; fuseau local clairement défini.
- Montants en entiers XOF ; quantités avec une précision maîtrisée et documentée.
- Archivage logique des référentiels utilisés dans des opérations.
- Les lignes de vente/achat conservent un instantané des libellés et prix nécessaires à l'historique.
- Le journal des mouvements sert de preuve métier ; les soldes courants sont vérifiables par rapprochement.

7. Règles métier transversales
   7.1 Numérotation
   Prévoir des numéros lisibles et uniques, par exemple :

- Vente : VTE-2026-000001
- Commande client : CMD-2026-000001
- Achat : ACH-2026-000001
- Réception : REC-2026-000001
- Livraison : LIV-2026-000001
- Inventaire : INV-2026-000001
- Dépense : DEP-2026-000001
  Les compteurs doivent être gérés en base dans une transaction afin d'éviter les doublons.
  7.2 Transactions et états
  Les documents suivent des états explicites : brouillon, confirmé/validé, partiellement traité, clôturé, annulé. Les changements d'état doivent être contrôlés par les services métier.

Toute opération confirmée qui touche plusieurs éléments (vente + stock + paiement + caisse + créance + consigne) est exécutée dans une transaction de base de données. En cas d'erreur, tout est annulé : aucun état partiel ne doit subsister.
7.3 Retours et annulations

- Une annulation doit référencer le document d'origine.
- Les quantités retournées ne peuvent pas dépasser les quantités vendues restant retournables.
- Le stock est réintégré uniquement si la marchandise est physiquement récupérée et revendable.
- Les marchandises cassées ou non revendables sont dirigées vers une sortie de stock adaptée.
- Le remboursement peut être en espèces, autre moyen ou avoir, selon le choix autorisé.
- Les écritures financières et de stock sont corrigées par contrepassation, jamais par suppression silencieuse.
  7.4 Disponibilité et conditionnements
  Chaque produit possède une unité de stock de base et des conditionnements de vente. Exemple : 1 casier = 24 bouteilles, si cette conversion est configurée.

Une vente de 2 casiers et 3 bouteilles retire 2 × 24 + 3 unités de base du stock de boissons. La capacité du conditionnement doit être configurable par produit et ne doit jamais être codée en dur.

La gestion des casiers/bouteilles vides reste distincte : vendre 2 casiers pleins peut également générer une remise d'emballages consignés selon la configuration du produit et le traitement choisi.
7.5 Prix et remises

- Un prix peut être défini par conditionnement et liste tarifaire.
- Le tarif par défaut est appliqué selon le type de client.
- Toute modification manuelle du prix doit être autorisée et journalisée.
- Les remises peuvent être en montant ou en pourcentage, avec limites par rôle.
- Le document confirmé conserve le prix réellement appliqué.
  7.6 Gestion des dates de péremption
  Le suivi par lot est activable par produit. Si activé, les sorties doivent appliquer une logique FEFO (premier lot à expirer, premier sorti), sous réserve de disponibilité et de validation. Les alertes distinguent les produits proches de la date configurée et les produits expirés.
  7.7 Rapprochements
  Prévoir des outils de vérification pour comparer :
- Stock courant et somme des mouvements.
- Solde client et ventes moins paiements/avoirs.
- Solde fournisseur et factures moins paiements/avoirs.
- Solde théorique de caisse et mouvements de caisse.
- Consignes dues et mouvements d'emballages.
  Les écarts détectés doivent être présentés et corrigés par une procédure dédiée, sans réparation silencieuse.

8. Sauvegarde, restauration et continuité
   8.1 Politique de sauvegarde

- Sauvegarde automatique quotidienne au premier démarrage ou à un moment paramétré lorsque l'application est ouverte.
- Sauvegarde à la fermeture propre de l'application.
- Sauvegarde manuelle à la demande.
- Option de copie sur un disque externe ou un dossier choisi.
- Rétention configurable, par exemple les 7 dernières sauvegardes quotidiennes et les 4 dernières sauvegardes hebdomadaires.
- Indication visible de la dernière sauvegarde réussie.
  L'application étant hors ligne, une tâche planifiée ne peut pas s'exécuter lorsque l'ordinateur est éteint ou que l'application n'est pas lancée, sauf mise en place ultérieure d'un service système. L'interface doit expliquer cette limite.
  8.2 Sécurité des sauvegardes
- Utiliser l'API de sauvegarde SQLite ou une méthode sûre permettant une copie cohérente de la base active.
- Ne pas copier brutalement un fichier SQLite actif si cela risque d'omettre les données du journal WAL.
- Vérifier l'intégrité de la copie (PRAGMA integrity_check).
- Enregistrer date, taille, résultat et emplacement.
- Conserver au moins une copie sur un support physiquement distinct lorsque cela est possible.
  8.3 Restauration
- Exiger une confirmation explicite et l'authentification d'un administrateur.
- Créer une sauvegarde de sécurité de la base actuelle avant restauration.
- Vérifier l'intégrité de la sauvegarde choisie.
- Fermer les connexions à la base et restaurer de manière contrôlée.
- Redémarrer/recharger l'application et afficher le résultat.
- Ne jamais écraser une base avec une sauvegarde invalide.
  8.4 Protection du poste
  Recommander le chiffrement complet du disque par les outils natifs du système (BitLocker ou FileVault). SQLite n'est pas chiffré par défaut ; si le chiffrement applicatif est requis, étudier une solution compatible telle que SQLCipher et ses contraintes de distribution.

9. Fonctionnement hors ligne et dépendances matérielles
   L'application doit fonctionner sans accès réseau pour toutes les fonctions incluses dans la V1.

Périphériques pris en charge sous réserve de leurs pilotes locaux :

- Imprimante de tickets 58 mm ou 80 mm.
- Imprimante A4.
- Lecteur de code-barres USB agissant comme clavier.
- Clavier et pavé numérique.
- Support de sauvegarde USB/externe.
  L'impression et les lecteurs doivent être testés sur les modèles réellement utilisés. Le logiciel ne doit pas supposer qu'une imprimante ou un lecteur est connecté.

10. Tests et critères d'acceptation
    Aucune phase ne doit être considérée comme terminée uniquement parce que l'écran s'affiche. Les parcours métier doivent être testés avec une base de démonstration puis avec des scénarios réalistes.
    10.1 Tests de base de données

- Création et migration d'une base neuve.
- Réouverture d'une base existante après mise à jour.
- Vérification des clés étrangères et index.
- Refus des montants/quantités invalides.
- Contrôle d'unicité des références et numéros de documents.
- Vérification de l'intégrité et du journal des mouvements.
  10.2 Scénarios métier obligatoires
  ID Scénario Résultat attendu
  T01 Créer un produit avec 1 casier = 24 bouteilles Conversion enregistrée et visible
  T02 Réceptionner 10 casiers Stock augmenté de 240 bouteilles de base
  T03 Vendre 2 casiers et 3 bouteilles Stock diminué de 51 bouteilles
  T04 Tenter de vendre au-delà du stock Vente bloquée ou procédure d'autorisation explicite
  T05 Vendre pour 150 000 F et encaisser 100 000 F Créance de 50 000 F
  T06 Encaisser ensuite 20 000 F Créance ramenée à 30 000 F, CA inchangé
  T07 Faire un retour partiel Stock, remboursement et document d'origine cohérents
  T08 Remettre 5 casiers consignés et en récupérer 3 Solde client de 2 casiers
  T09 Réceptionner une commande fournisseur partiellement Seules les quantités reçues entrent en stock
  T10 Enregistrer une dépense en espèces Solde théorique de caisse diminué
  T11 Enregistrer un paiement Mobile Money Paiement visible, caisse espèces inchangée
  T12 Clôturer une caisse avec écart Écart calculé, commenté et audité
  T13 Valider un inventaire avec manque Mouvement correctif tracé
  T14 Générer un rapport Excel et PDF Totaux identiques aux données sources
  T15 Sauvegarder puis restaurer Toutes les données et relations sont retrouvées
  T16 Fermer brutalement pendant une validation simulée Aucune transaction partielle incohérente
  T17 Modifier le prix d'achat après une ancienne vente Marge historique inchangée
  T18 Désactiver un utilisateur Son historique reste consultable

  10.3 Critères d'acceptation de la V1

- Le logiciel démarre et fonctionne sans Internet.
- La base de données est créée automatiquement au premier démarrage.
- Le catalogue est configurable par un administrateur.
- Les achats réceptionnés et ventes validées modifient le stock de façon cohérente.
- Les conditionnements convertissent correctement les quantités.
- Les consignes sont suivies séparément des produits vendus.
- Les paiements partiels et soldes clients/fournisseurs sont corrects.
- La caisse distingue espèces et paiements non espèces.
- Les marges historiques utilisent les coûts mémorisés à la vente.
- Les rapports Excel et PDF concordent avec les données sources.
- Une sauvegarde peut être créée et restaurée avec contrôle d'intégrité.
- Les opérations sensibles sont protégées et journalisées.
- Les versions Windows et macOS sont installables et conservent les données après mise à jour.

11. Plan d'implémentation par phases
    Phase 0 — Cadrage et prototype technique
    Travaux : valider les flux métier, figer les conventions de données, créer le dépôt Git, tester PySide6, SQLite, impression et packaging minimal sur chaque système.

Livrable : prototype qui démarre sur Windows et macOS, ouvre une base locale et affiche une fenêtre principale.

Validation : lancement hors ligne, écriture/lecture en base, fermeture et réouverture sans perte.
Phase 1 — Fondations et catalogue
Travaux : architecture en couches, migrations, connexion, utilisateurs, rôles, paramètres, catégories, marques, unités, conditionnements, produits et tarifs.

Livrable : gestion complète du catalogue avec import initial depuis Excel/CSV.

Validation : création, modification, archivage, recherche, conversion des conditionnements et contrôle des permissions.
Phase 2 — Stocks, achats et consignes
Travaux : journal des mouvements, soldes, fournisseurs, commandes d'achat, réceptions, coûts, inventaires de départ, types d'emballages et suivi des consignes.

Livrable : stock fiable et traçable, réception d'achat et suivi des emballages.

Validation : scénarios T01, T02, T08 et T09.
Phase 3 — Caisse et ventes
Travaux : écran POS, recherche rapide, pavé numérique, panier, listes de prix, remises, paiements mixtes, tickets, ventes à crédit et retours.

Livrable : prise de commande et vente opérationnelle.

Validation : scénarios T03 à T07 et T17.
Phase 4 — Clients, livraisons et finances
Travaux : commandes clients, relevés, crédits, paiements affectés, bons de livraison, sessions de caisse, dépenses et dettes fournisseurs.

Livrable : suivi commercial et financier complet.

Validation : scénarios T05, T06, T10, T11 et T12.
Phase 5 — Inventaires, analyses et rapports
Travaux : inventaires guidés, tableau de bord, valorisation, marges, rapports filtrés, exports Excel/PDF et documents imprimables.

Livrable : pilotage de l'activité.

Validation : scénarios T13, T14 et rapprochements de soldes.
Phase 6 — Sécurité, sauvegarde et stabilisation
Travaux : audit, permissions fines, sauvegarde automatique, restauration, contrôle d'intégrité, tests de régression, gestion des erreurs et optimisation.

Livrable : version candidate à la distribution.

Validation : scénarios T15, T16 et T18, plus tests de restauration sur un autre poste.
Phase 7 — Packaging et distribution
Travaux : construction Windows, création de l'installateur, création de l'application macOS et du DMG, signature/notarisation si nécessaire, icônes, licence, assistant de premier lancement et documentation utilisateur.

Livrable : installateur Windows .exe ou .msi et image disque macOS .dmg.

Validation : installation propre, lancement hors ligne, mise à jour sans perte de données, désinstallation sans suppression involontaire des données. 12. Données de démonstration et mise en service
Créer un jeu de données de démonstration isolé de la base réelle, comprenant :

- Catégories réalistes de boissons.
- Produits et conditionnements variés.
- Prix de démonstration en FCFA, clairement identifiés comme exemples.
- Plusieurs clients et fournisseurs fictifs.
- Quelques achats, réceptions, ventes, crédits, paiements et retours.
- Emballages consignés avec casiers et bouteilles.
- Dépenses et clôtures de caisse fictives.
  Prévoir un assistant de première configuration pour saisir le nom du dépôt, les coordonnées, les utilisateurs, le fond initial de caisse et importer le catalogue existant.

L'import doit proposer une prévisualisation, détecter les doublons et erreurs, permettre de corriger les lignes et conserver un rapport d'import. Aucun import ne doit écraser les données existantes sans confirmation explicite. 13. Documentation à livrer

1. README.md : présentation, prérequis de développement et lancement.
2. IMPLEMENTATIONS.md : présent cahier des charges et suivi des phases.
3. USER_GUIDE.md : guide utilisateur illustré.
4. ADMIN_GUIDE.md : configuration, utilisateurs, sauvegardes et restauration.
5. DATABASE.md : schéma, migrations et règles de conservation.
6. RELEASE_NOTES.md : historique des versions et changements.
7. Procédure de sauvegarde avant mise à jour et de restauration après incident.
8. Décisions à confirmer pendant le cadrage détaillé
   Les choix ci-dessous ne bloquent pas la conception générale, mais doivent être confirmés avant les modules concernés :
9. Liste exacte des boissons, marques, formats et conditionnements du dépôt.
10. Nombre de bouteilles par casier/carton selon chaque référence.
11. Types d'emballages consignés et montant associé à chacun.
12. Politique de vente à crédit : autorisation, plafond, échéance et blocage éventuel.
13. Tarifs : détail, demi-gros, gros, revendeur, client professionnel.
14. Méthode de valorisation : coût moyen pondéré recommandé pour la V1.
15. Suivi des lots et dates de péremption : activé pour tous les produits concernés ou seulement certains.
16. Documents nécessaires : ticket, facture, reçu, bon de commande et bon de livraison.
17. Modèle d'imprimante de tickets et imprimante A4 disponibles.
18. Règles fiscales et mentions à imprimer, à valider avec le responsable et son conseil comptable.
19. Besoin éventuel de plusieurs ordinateurs partageant les données sur un réseau local.
20. Besoin éventuel de plusieurs dépôts physiques, hors périmètre initial.
21. Definition of Done — définition d'une fonctionnalité terminée
    Une fonctionnalité est considérée comme terminée lorsque :

- son écran est implémenté et cohérent avec le système de navigation ;
- les validations de formulaire et messages d'erreur sont présents ;
- les règles métier sont dans un service testable ;
- les données sont persistées avec contraintes et migrations ;
- les permissions sont vérifiées ;
- les actions sensibles sont journalisées ;
- les tests unitaires et d'intégration correspondants passent ;
- les états vides, chargement, succès et erreur sont traités ;
- l'écran reste utilisable au clavier ;
- les documents et rapports concernés sont mis à jour ;
- la fonctionnalité fonctionne hors ligne ;
- les critères d'acceptation associés sont validés.

16. Ordre de priorité produit
    Priorité Fonctions
    P0 — Indispensable Base locale, catalogue, conditionnements, stock, achats/réceptions, ventes/caisse, clients, paiements, sauvegarde
    P1 — Forte valeur métier Consignes, crédits avancés, livraisons, fournisseurs, dépenses, inventaires, rapports Excel/PDF
    P2 — Amélioration Prévisions de réapprovisionnement, codes-barres avancés, lots/péremption, analyse comparative, tableaux de rentabilité évolués
    P3 — Évolution future Réseau local multi-postes, synchronisation distante optionnelle, intégrations Mobile Money, application compagnon

La priorité P0 doit être stable avant d'ajouter des fonctionnalités avancées. Il vaut mieux livrer un cycle achat-stock-vente-paiement fiable qu'une grande quantité d'écrans incomplets. 17. Résultat final attendu
À la fin du projet, GestDepot doit être un logiciel de gestion de dépôt de boissons réellement exploitable au quotidien, qui :

- fonctionne sans Internet ;
- s'installe sur Windows et macOS ;
- conserve ses données localement ;
- permet de configurer librement produits, conditionnements et tarifs ;
- suit les marchandises et emballages consignés ;
- relie achats, stocks, ventes, clients, fournisseurs, caisse et livraisons ;
- calcule les marges à partir des coûts historiques ;
- fournit des rapports Excel et PDF ;
- sauvegarde et restaure les données de manière vérifiée ;
- protège les opérations sensibles et conserve leur historique.
  Règle directrice du développement : chaque étape doit être livrée avec ses tests, démontrée sur un scénario métier réaliste et validée avant de passer à la suivante.
