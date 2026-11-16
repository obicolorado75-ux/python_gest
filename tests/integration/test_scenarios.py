"""Scénarios métier obligatoires T01–T14, T17, T18 (§10.2)."""
import pytest
from sqlalchemy import select

from gestdepot.database.models import ProductCostHistory, SaleLine, StockMovement
from gestdepot.database.session import session_scope
from gestdepot.services.catalog_service import CatalogError
from gestdepot.services.sales_service import SalesError
from gestdepot.services.stock_service import StockError


class TestCatalogue:
    def test_t01_conditionnement(self, admin, catalog, product_with_casier):
        """T01 : créer un produit avec 1 casier = 24 bouteilles."""
        product, packaging = product_with_casier
        assert packaging.factor == 24
        assert catalog.factor_of(packaging.id) == 24
        assert catalog.factor_of(None) == 1

    def test_reference_unique(self, admin, catalog, product_with_casier):
        with pytest.raises(CatalogError):
            catalog.create_product(reference="SOD-33CL", name="Doublon",
                                   base_unit_id=catalog.list_units()[0].id)

    def test_facteur_invalide_refuse(self, admin, catalog, product_with_casier):
        product, _ = product_with_casier
        with pytest.raises(CatalogError):
            catalog.add_packaging(product.id, "Carton", factor=0)

    def test_archive_sans_suppression(self, admin, catalog, product_with_casier):
        product, _ = product_with_casier
        catalog.archive_product(product.id)
        archived = catalog.get(product.id)
        assert archived.archived is True and archived.active is False
        assert catalog.list_products() == []

    def test_recherche_par_nom_et_reference(self, admin, catalog,
                                            product_with_casier):
        product, _ = product_with_casier
        assert [p.id for p in catalog.list_products("Soda")] == [product.id]
        assert [p.id for p in catalog.list_products("SOD-")] == [product.id]

    def test_tarif_par_conditionnement(self, admin, catalog, product_with_casier):
        product, packaging = product_with_casier
        detail = catalog.list_price_lists()[0].id
        assert catalog.resolve_price(product.id, detail, packaging.id) == 3600
        assert catalog.resolve_price(product.id, detail, None) == 150
        # sans liste précisée, le tarif par défaut (Détail) s'applique
        assert catalog.resolve_price(product.id, None, packaging.id) == 3600

    def test_import_previsualisation(self, admin, catalog):
        unit = catalog.list_units()[0].name
        rows = [{"reference": "IMP-1", "name": "Produit importé", "unit": unit,
                 "cost": 250},
                {"reference": "IMP-1", "name": "Doublon", "unit": unit, "cost": 250},
                {"reference": "", "name": "Sans référence", "unit": "Inconnue"}]
        report = catalog.preview_import(rows)
        assert report[0]["ok"] is True
        assert any("double" in error for error in report[1]["errors"])
        assert report[2]["ok"] is False
        with pytest.raises(CatalogError):
            catalog.import_products(rows)
        created = catalog.import_products(rows[:1])
        assert created[0].current_cost == 250


class TestStock:
    def test_t02_reception_augmente_le_stock(self, admin, stock, order_with_lines,
                                             product_with_casier):
        """T02 : réceptionner 10 casiers => +240 bouteilles de base."""
        product, _ = product_with_casier
        order, line_id = order_with_lines
        assert stock.available(product.id) == 0  # une commande ne touche pas le stock
        receipt = stock.receive(order.id, [{"order_line_id": line_id,
                                            "quantity": 240, "unit_cost": 100}])
        assert stock.available(product.id) == 240
        assert receipt.total_amount == 24_000

    def test_t09_reception_partielle(self, admin, stock, order_with_lines,
                                     product_with_casier):
        """T09 : seules les quantités reçues entrent en stock, reliquat conservé."""
        product, _ = product_with_casier
        order, line_id = order_with_lines
        stock.receive(order.id, [{"order_line_id": line_id, "quantity": 120,
                                 "unit_cost": 100}])
        assert stock.available(product.id) == 120
        with session_scope() as session:
            from gestdepot.database.models import PurchaseOrder
            refreshed = session.get(PurchaseOrder, order.id)
            assert refreshed.status == "partially_received"
            assert refreshed.lines[0].received_qty == 120
        # reliquat : 120 restants, sur-réception refusée
        with pytest.raises(StockError):
            stock.receive(order.id, [{"order_line_id": line_id, "quantity": 200}])
        stock.receive(order.id, [{"order_line_id": line_id, "quantity": 120,
                                 "unit_cost": 100}])
        assert stock.available(product.id) == 240

    def test_facture_et_solde_fournisseur(self, admin, stock, order_with_lines,
                                          supplier, product_with_casier):
        order, line_id = order_with_lines
        stock.receive(order.id, [{"order_line_id": line_id, "quantity": 240,
                                 "unit_cost": 100}])
        with session_scope() as session:
            from gestdepot.database.models import Supplier
            refreshed = session.get(Supplier, supplier.id)
            assert refreshed.balance == 24_000

    def test_cmp_et_journal(self, admin, stock, product_with_casier):
        """Le solde courant reste égal au journal des mouvements."""
        product, _ = product_with_casier
        stock.initial_stock(product.id, 100, unit_cost=100)
        stock.adjust(product.id, 100, "mouvement_initial", comment="test")
        with session_scope() as session:
            movements = list(session.scalars(select(StockMovement).where(
                StockMovement.product_id == product.id)))
        assert sum(m.quantity for m in movements) == stock.balance(product.id).quantity
        assert stock.reconcile() == []

    def test_mouvement_negatif_refuse(self, admin, stock, product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 10, unit_cost=100)
        with pytest.raises(StockError):
            stock.adjust(product.id, -50, "perte")

    def test_quantite_nulle_refusee(self, admin, stock, product_with_casier):
        product, _ = product_with_casier
        with pytest.raises(StockError):
            stock.adjust(product.id, 0, "perte")

    def test_cout_moyen_pondere(self, admin, stock, supplier, product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 10, unit_cost=100)
        order = stock.create_purchase_order(supplier.id, [{
            "product_id": product.id, "designation": product.name,
            "quantity": 10, "quantity_display": 10, "unit_cost": 300}])
        with session_scope() as session:
            from gestdepot.database.models import PurchaseOrderLine
            line_id = session.scalar(select(PurchaseOrderLine.id))
        stock.receive(order.id, [{"order_line_id": line_id, "quantity": 10,
                                 "unit_cost": 300}])
        # (10×100 + 10×300) / 20 = 200
        assert stock.balance(product.id).weighted_avg_cost == 200

    def test_alertes_seuil(self, admin, stock, product_with_casier):
        product, _ = product_with_casier
        product_id = product.id
        with session_scope() as session:
            refreshed = session.get(type(product), product_id)
            refreshed.min_threshold = 50
        stock.initial_stock(product_id, 10, unit_cost=100)
        alerts = stock.low_stock_products()
        assert (product_id, 10, "sous_seuil") in alerts


class TestVentes:
    def test_t03_vente_mixte(self, admin, stock, sales, stocked_product, catalog):
        """T03 : vendre 2 casiers + 3 bouteilles => -51 bouteilles."""
        product, packaging = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": packaging.id,
                    "quantity_display": 2},
                   {"product_id": product.id, "packaging_id": None,
                    "quantity_display": 3}],
            payment_method="especes", paid_amount=7650, price_list_id=detail)
        assert stock.available(product.id) == 240 - 51
        assert sale.total_amount == 2 * 3600 + 3 * 150  # 7650
        assert sale.paid_amount == 7650

    def test_t04_stock_insuffisant(self, admin, stock, sales, product_with_casier,
                                   catalog):
        """T04 : vente au-delà du stock bloquée."""
        product, packaging = product_with_casier
        stock.initial_stock(product.id, 24, unit_cost=100)
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": packaging.id,
                        "quantity_display": 2}],
                payment_method="especes", paid_amount=7200,
                price_list_id=catalog.list_price_lists()[0].id)
        assert stock.available(product.id) == 24  # rien n'a bougé

    def test_quantite_nulle_ou_negative(self, admin, sales, stocked_product,
                                        catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        for quantity in (0, -3):
            with pytest.raises(SalesError):
                sales.confirm_sale(
                    items=[{"product_id": product.id, "packaging_id": None,
                            "quantity_display": quantity}],
                    payment_method="especes", paid_amount=0,
                    price_list_id=detail)

    def test_t05_t06_credit_partiel(self, admin, stock, sales, stocked_product,
                                    catalog):
        """T05/T06 : créance de 50 000 puis règlement partiel, CA inchangé."""
        product, _ = stocked_product
        gros = catalog.list_price_lists()[1].id
        catalog.set_price(product.id, gros, unit_price=120)
        with session_scope() as session:
            from gestdepot.database.models import StockBalance
            session.get(StockBalance, product.id).quantity = 2000
        customer = sales.create_customer(code="CLI-1", name="Bar Le Baobab",
                                        customer_type="gros",
                                        credit_limit=1_000_000)
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 1250}],
            payment_method="especes", paid_amount=100_000,
            customer_id=customer.id, price_list_id=gros)
        assert sale.total_amount == 150_000
        assert sales.customer_balance(customer.id) == 50_000
        ca_before = sale.total_amount

        sales.pay_credit(customer.id, 20_000)
        assert sales.customer_balance(customer.id) == 30_000
        with session_scope() as session:
            stored = session.get(type(sale), sale.id)
            assert stored.total_amount == ca_before  # CA inchangé (T06)

        # un paiement ne peut dépasser le solde restant
        sales.pay_credit(customer.id, 100_000)
        assert sales.customer_balance(customer.id) == 0

    def test_plafond_credit_bloque(self, admin, stock, sales, stocked_product,
                                   catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        customer = sales.create_customer(code="CLI-P", name="Client Plafonné",
                                        credit_limit=1_000)
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": 10}],
                payment_method="especes", paid_amount=0,
                customer_id=customer.id, price_list_id=detail)

    def test_credit_sans_client_refuse(self, admin, sales, stocked_product, catalog):
        product, _ = stocked_product
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": 5}],
                payment_method="especes", paid_amount=100,
                price_list_id=catalog.list_price_lists()[0].id)

    def test_t07_retour_partiel(self, admin, stock, sales, stocked_product, catalog):
        """T07 : retour partiel, stock réintégré, document d'origine cohérent."""
        product, packaging = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": packaging.id,
                    "quantity_display": 5}],
            payment_method="especes", paid_amount=18_000, price_list_id=detail)
        line_id = sale.lines[0].id
        ret = sales.return_sale(sale.id, [{"sale_line_id": line_id,
                                          "quantity": 24}])
        assert ret.total_amount == 3600
        assert stock.available(product.id) == 240 - 120 + 24
        with session_scope() as session:
            from gestdepot.database.models import Sale
            assert session.get(Sale, sale.id).status == "partially_returned"
        # retour excessif refusé
        with pytest.raises(SalesError):
            sales.return_sale(sale.id, [{"sale_line_id": line_id,
                                        "quantity": 200}])

    def test_retour_non_revendable_sans_reintegration(self, admin, stock, sales,
                                                      stocked_product, catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1500, price_list_id=detail)
        before = stock.available(product.id)
        sales.return_sale(sale.id, [{"sale_line_id": sale.lines[0].id,
                                     "quantity": 4, "resellable": False}],
                          reason="Bouteilles cassées")
        assert stock.available(product.id) == before  # pas de réintégration

    def test_remboursement_limite_a_lencaisse(self, admin, sales, cash,
                                              stocked_product, catalog):
        """On ne rembourse pas plus que ce qui a été encaissé."""
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        cash_session = cash.open_session(opening_fund=0)
        customer = sales.create_customer(code="CLI-R", name="Client Crédit",
                                        credit_limit=1_000_000)
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],   # 1500
            payment_method="especes", paid_amount=0, customer_id=customer.id,
            price_list_id=detail)
        sales.return_sale(sale.id, [{"sale_line_id": sale.lines[0].id,
                                     "quantity": 10}], reason="Retour")
        # aucun encaissement : la caisse ne doit pas sortir d'espèces
        assert cash.theoretical_amount(cash_session.id) == 0
        assert sales.customer_balance(customer.id) == 0

    def test_annulation_tracee(self, admin, stock, sales, stocked_product, catalog):
        product, _ = stocked_product
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 12}],
            payment_method="especes", paid_amount=1800,
            price_list_id=catalog.list_price_lists()[0].id)
        sales.cancel_sale(sale.id, "Erreur de saisie")
        assert stock.available(product.id) == 240  # stock rétabli
        with session_scope() as session:
            from gestdepot.database.models import Sale
            assert session.get(Sale, sale.id).status == "cancelled"
            # la vente n'est jamais supprimée
            assert session.get(Sale, sale.id) is not None
        with pytest.raises(SalesError):
            sales.cancel_sale(sale.id, "Deuxième annulation")


class TestConsignes:
    def test_t08_consignes_client(self, admin, deposit):
        """T08 : 5 casiers remis, 3 retournés => solde client de 2 casiers."""
        from gestdepot.services.sales_service import SalesService
        packaging = deposit.create_packaging("CAS-BIE", "Casier bière", 500)
        customer = SalesService().create_customer(code="CLI-D", name="Client Dépôt")
        deposit.move(packaging.id, 5, "remis_client", customer_id=customer.id)
        assert deposit.customer_balance(customer.id)[packaging.id] == 5
        deposit.move(packaging.id, -3, "retourne_client", customer_id=customer.id)
        assert deposit.customer_balance(customer.id)[packaging.id] == 2
        assert deposit.customer_balance_value(customer.id) == 1000
        # retour supérieur au solde dû refusé
        with pytest.raises(Exception):
            deposit.move(packaging.id, -5, "retourne_client",
                         customer_id=customer.id)

    def test_consigne_separee_du_chiffre_affaires(self, admin, stock, sales,
                                                  deposit, stocked_product,
                                                  catalog):
        product, _ = stocked_product
        packaging = deposit.create_packaging("CAS-2", "Casier", 500)
        detail = catalog.list_price_lists()[0].id
        customer = sales.create_customer(code="CLI-C", name="Client Consigne")
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=2000, customer_id=customer.id,
            price_list_id=detail, deposit_packaging_id=packaging.id,
            deposit_qty=2)
        assert sale.total_amount == 1500 + 1000
        assert sale.deposit_amount == 1000


class TestCaisse:
    def test_t10_depense_diminue_la_caisse(self, admin, cash):
        """T10 : une dépense en espèces diminue le solde théorique."""
        cash_session = cash.open_session(opening_fund=50_000)
        category = cash.list_expense_categories()[0]
        cash.add_expense(10_000, category.id, beneficiary="Carburant")
        assert cash.theoretical_amount(cash_session.id) == 40_000

    def test_t11_mobile_money_hors_caisse(self, admin, cash, stock, sales,
                                          stocked_product, catalog):
        """T11 : un paiement Mobile Money ne modifie pas la caisse espèces."""
        product, packaging = stocked_product
        cash_session = cash.open_session(opening_fund=0)
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": packaging.id,
                    "quantity_display": 4}],
            payment_method="orange_money", paid_amount=14_400,
            price_list_id=catalog.list_price_lists()[0].id)
        assert cash.theoretical_amount(cash_session.id) == 0
        totals = cash.movements_by_method(cash_session.id)
        assert totals.get("orange_money") == 14_400  # suivi séparément

    def test_t12_cloture_avec_ecart(self, admin, cash):
        """T12 : écart calculé, commenté et audité."""
        cash_session = cash.open_session(opening_fund=50_000)
        category = cash.list_expense_categories()[0]
        cash.add_expense(10_000, category.id)
        closed = cash.close_session(cash_session.id, counted_amount=39_000,
                                    comment="Manquant constaté")
        assert closed.theoretical_amount == 40_000
        assert closed.difference == -1_000
        assert closed.status == "closed"
        with pytest.raises(Exception):
            cash.close_session(cash_session.id, counted_amount=0)

    def test_double_ouverture_refusee(self, admin, cash):
        cash.open_session(opening_fund=0)
        with pytest.raises(Exception):
            cash.open_session(opening_fund=0)

    def test_t17_marge_historique(self, admin, stock, sales, catalog,
                                  stocked_product):
        """T17 : modifier le coût après une vente ne change pas la marge historique."""
        product, _ = stocked_product
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1500,
            price_list_id=catalog.list_price_lists()[0].id)
        line = sale.lines[0]
        assert line.unit_cost == 100
        catalog.set_cost(product.id, 200)
        with session_scope() as session:
            stored = session.get(SaleLine, line.id)
            assert stored.unit_cost == 100
            history = list(session.scalars(select(ProductCostHistory).where(
                ProductCostHistory.product_id == product.id)))
            assert [entry.cost for entry in history] == [100, 200]


class TestInventaire:
    def test_t13_inventaire_avec_manque(self, admin, stock, inventory,
                                        product_with_casier):
        """T13 : valider un inventaire avec manque crée un mouvement correctif."""
        product, _ = product_with_casier
        stock.initial_stock(product.id, 100, unit_cost=100)
        session = inventory.start_session()
        inventory.set_counted(session.id, product.id, 97)
        summary = inventory.validate(session.id)
        assert summary["adjusted_lines"] == 1
        assert summary["gap_quantity"] == -3
        assert stock.available(product.id) == 97
        assert stock.reconcile() == []
        with session_scope() as db_session:
            corrections = list(db_session.scalars(select(StockMovement).where(
                StockMovement.reason == "correction_inventaire")))
            assert len(corrections) == 1 and corrections[0].quantity == -3

    def test_inventaire_valide_non_modifiable(self, admin, inventory,
                                              product_with_casier):
        product, _ = product_with_casier
        session = inventory.start_session()
        inventory.validate(session.id)
        with pytest.raises(Exception):
            inventory.set_counted(session.id, product.id, 5)
        with pytest.raises(Exception):
            inventory.validate(session.id)


class TestSecurite:
    def test_login_message_neutre(self, db):
        from gestdepot.security import AuthError, auth
        with pytest.raises(AuthError):
            auth.login("admin", "mauvais")

    def test_permission_refusee(self, db):
        from gestdepot.database.models import Role, User
        from gestdepot.database.session import session_scope
        from gestdepot.security import auth, hash_password
        with session_scope() as session:
            role = session.scalar(select(Role).where(Role.name == "Caissier"))
            session.add(User(username="cai", password_hash=hash_password("secret"),
                             role_id=role.id))
        auth.login("cai", "secret")
        with pytest.raises(PermissionError):
            auth.Session.current().require("users.manage")
        assert auth.Session.current().has_permission("sales.create")

    def test_t18_desactivation_conserve_historique(self, admin):
        from gestdepot.services.admin_service import AdminService
        service = AdminService()
        user = service.create_user("vendeur", "secret123", "Caissier",
                                   full_name="Vendeur Test")
        service.deactivate_user(user.id)
        users = {u.username: u for u in service.list_users()}
        assert users["vendeur"].active is False  # jamais supprimé

    def test_operations_sensibles_journalisees(self, admin):
        from gestdepot.services.admin_service import AdminService
        logs = AdminService().audit_logs(limit=50)
        actions = {entry.action for entry in logs}
        assert "login_ok" in actions


class TestSauvegarde:
    def test_t15_sauvegarde_et_restauration(self, admin, tmp_path, stock,
                                            product_with_casier):
        """T15 : sauvegarder puis restaurer retrouve les données."""
        from gestdepot.services.backup_service import BackupService
        product, _ = product_with_casier
        stock.initial_stock(product.id, 42, unit_cost=100)
        backup = BackupService()
        record = backup.backup(destination=str(tmp_path / "sauvegardes"))
        assert record.success is True
        assert backup.verify(record.path) is True

        # on modifie la base puis on restaure
        stock.adjust(product.id, 8, "mouvement_initial")
        assert stock.available(product.id) == 50
        backup.restore(record.path)
        from gestdepot.security import auth
        auth.login("admin", "secret")
        assert stock.available(product.id) == 42

    def test_sauvegarde_invalide_refusee(self, admin, tmp_path):
        from gestdepot.services.backup_service import BackupError, BackupService
        bogus = tmp_path / "faux.db"
        bogus.write_text("ceci n'est pas une base sqlite")
        with pytest.raises(BackupError):
            BackupService().restore(str(bogus))
