"""Fenêtre principale : navigation latérale, barre supérieure, pages (§5.1, §5.2)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import app_paths
from ..security import auth
from ..services.admin_service import AdminService
from ..services.backup_service import BackupError, BackupService
from ..services.cash_service import CashService
from ..services.catalog_service import CatalogService
from ..services.deposit_service import DepositService
from ..services.inventory_service import InventoryService
from ..services.reporting_service import ReportingService
from ..services.sales_service import SalesService
from ..services.stock_service import StockService
from .pages.cash_page import CashPage
from .pages.customers_page import CustomersPage
from .pages.dashboard_page import DashboardPage
from .pages.deposits_page import DepositsPage
from .pages.inventory_page import InventoryPage
from .pages.products_page import ProductsPage
from .pages.purchases_page import PurchasesPage
from .pages.reports_page import ReportsPage
from .pages.sales_page import SalesPage
from .pages.settings_page import SettingsPage
from .pages.stock_page import StockPage

NAVIGATION = [
    ("Tableau de bord", "dashboard", "Tableau de bord"),
    ("Ventes / Caisse", "sales", "Vendre et encaisser"),
    ("Produits et catalogue", "products", "Produits, conditionnements, tarifs"),
    ("Stocks et mouvements", "stock", "Stock et journal des mouvements"),
    ("Consignes et emballages", "deposits", "Emballages et comptes de consigne"),
    ("Clients et crédits", "customers", "Clients, créances, règlements"),
    ("Achats et réapprovisionnement", "purchases", "Fournisseurs et réceptions"),
    ("Caisse et dépenses", "cash", "Sessions de caisse et dépenses"),
    ("Inventaires", "inventory", "Comptage physique et écarts"),
    ("Marges et rapports", "reports", "Rapports, exports Excel / PDF"),
    ("Paramètres et sauvegarde", "settings", "Paramètres, utilisateurs, sauvegarde"),
]

PAGES = {
    "dashboard": DashboardPage,
    "sales": SalesPage,
    "products": ProductsPage,
    "stock": StockPage,
    "deposits": DepositsPage,
    "customers": CustomersPage,
    "purchases": PurchasesPage,
    "cash": CashPage,
    "inventory": InventoryPage,
    "reports": ReportsPage,
    "settings": SettingsPage,
}


class MainWindow(QMainWindow):
    def __init__(self, mode: str = "desktop"):
        super().__init__()
        session = auth.Session.current()
        self.mode = mode
        name = session.user.full_name or session.user.username if session else ""
        self.setWindowTitle(f"GestDepot — {name}")
        self.resize(1280, 800)
        self.setMinimumSize(1060, 660)

        self.services = {
            "catalog": CatalogService(),
            "stock": StockService(),
            "sales": SalesService(),
            "cash": CashService(),
            "deposit": DepositService(),
            "inventory": InventoryService(),
            "reporting": ReportingService(),
            "backup": BackupService(),
            "admin": AdminService(),
        }
        self.pages: dict[str, QWidget] = {}
        self._build()
        self._select("dashboard")
        self._check_daily_backup()

    # --- construction de l'interface -------------------------------------
    def _build(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        content.addWidget(self.stack, 1)
        root.addLayout(content, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Mode hors ligne — base locale : "
                                     f"{app_paths.database_path()}")

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setStyleSheet("#TopBar {background: #12324f; color: white;}")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 8, 18, 8)
        brand = QLabel("GestDepot")
        brand.setStyleSheet("font-size: 17px; font-weight: 700; color: white;")
        layout.addWidget(brand)

        session = auth.Session.current()
        company = self.services["admin"].company_settings().name
        depot = QLabel(f"  ·  {company}")
        depot.setStyleSheet("color: #cfe0ef;")
        layout.addWidget(depot)
        layout.addStretch(1)

        self.backup_label = QLabel()
        self.backup_label.setStyleSheet("color: #cfe0ef; font-size: 11px;")
        layout.addWidget(self.backup_label)
        today = QLabel(datetime.now().strftime("%d/%m/%Y"))
        today.setStyleSheet("color: #cfe0ef; margin-left: 14px;")
        layout.addWidget(today)

        if session:
            account = QLabel(f"  {session.user.full_name or session.user.username}")
            account.setStyleSheet("color: white; font-weight: 600; margin-left: 14px;")
            layout.addWidget(account)
        logout = QPushButton("Déconnexion")
        logout.setStyleSheet(
            "QPushButton {background: #1d4b6e; color: #ffffff; border: 1px solid "
            "#3a6f95; border-radius: 4px; padding: 5px 10px;}"
            "QPushButton:hover {background: #2a6b96;}")
        logout.clicked.connect(self._logout)
        layout.addWidget(logout)
        self._refresh_backup_label()
        return bar

    def _refresh_backup_label(self) -> None:
        try:
            last = self.services["backup"].last_successful()
        except Exception:  # pragma: no cover
            last = None
        if last is None:
            self.backup_label.setText("Aucune sauvegarde")
        else:
            stamp = last.at.strftime("%d/%m/%Y %H:%M")
            self.backup_label.setText(f"Dernière sauvegarde : {stamp}")

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(272)
        side.setStyleSheet("#Sidebar {background: #f4f6f9; border-right: 1px solid #dde3ea;}")
        layout = QVBoxLayout(side)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(4)
        self.nav_buttons: dict[str, QPushButton] = {}
        for label, key, tooltip in NAVIGATION:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton {text-align: left; padding: 9px 12px; border: none;"
                " border-radius: 6px; color: #23303c; font-size: 12px;}"
                "QPushButton:hover {background: #e4eaf1;}"
                "QPushButton:checked {background: #12324f; color: white;"
                " font-weight: 600;}")
            button.clicked.connect(lambda _=False, k=key: self._select(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch(1)
        version = QLabel("GestDepot 0.1 — hors ligne")
        version.setStyleSheet("color: #7a8794; font-size: 10px;")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        return side

    # --- navigation -------------------------------------------------------
    def _select(self, key: str) -> None:
        if key not in self.pages:
            page = PAGES[key](self.services)
            self.pages[key] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self.pages[key])
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        page = self.pages[key]
        try:
            page.refresh()
        except Exception as exc:  # pragma: no cover - défensif
            QMessageBox.warning(self, "Erreur", f"Impossible d'ouvrir l'écran : {exc}")

    def _logout(self) -> None:
        auth.Session.logout()
        self.close()
        QMessageBox.information(self, "Déconnexion",
                                "Session fermée. Relancez l'application "
                                "pour vous reconnecter.")

    # --- sauvegarde automatique quotidienne (§8.1) -------------------------
    def _check_daily_backup(self) -> None:
        try:
            backup = self.services["backup"]
            if backup.daily_backup_needed():
                QTimer.singleShot(800, self._run_daily_backup)
        except Exception:  # pragma: no cover
            pass

    def _run_daily_backup(self) -> None:
        try:
            record = self.services["backup"].backup(label="quotidienne")
            self.statusBar().showMessage(
                f"Sauvegarde quotidienne créée : {record.path}", 8000)
            self._refresh_backup_label()
        except (BackupError, PermissionError, Exception) as exc:  # pragma: no cover
            self.statusBar().showMessage(f"Sauvegarde automatique impossible : {exc}",
                                         12000)

    def closeEvent(self, event) -> None:  # noqa: N802 (API Qt)
        try:
            if auth.Session.current() is not None and \
                    self.services["backup"].should_backup_on_close():
                # sauvegarde à la fermeture propre (§8.1), désactivable
                self.services["backup"].backup(label="fermeture")
        except Exception:  # pragma: no cover
            pass
        super().closeEvent(event)
