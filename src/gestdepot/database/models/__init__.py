"""Import central de tous les modèles + création du schéma."""
from .base import Base
from .catalog import (
                      Brand,
                      Category,
                      PriceList,
                      Product,
                      ProductBarcode,
                      ProductCostHistory,
                      ProductPackaging,
                      ProductPrice,
                      Unit,
)
from .finance import (
                      BackupHistory,
                      CashMovement,
                      CashSession,
                      CustomerOrder,
                      CustomerOrderLine,
                      Delivery,
                      DeliveryLine,
                      DocumentSequence,
                      Expense,
                      ExpenseCategory,
                      GeneratedDocument,
)
from .packaging import DepositMovement, ReturnablePackaging
from .purchases import (
                      GoodsReceipt,
                      GoodsReceiptLine,
                      PurchaseOrder,
                      PurchaseOrderLine,
                      Supplier,
                      SupplierInvoice,
                      SupplierPayment,
)
from .sales import (
                      Customer,
                      CustomerCreditEvent,
                      CustomerPayment,
                      PaymentAllocation,
                      Sale,
                      SaleLine,
                      SaleReturn,
                      SaleReturnLine,
)
from .security import AppSetting, AuditLog, CompanySettings, Permission, Role, RolePermission, User
from .stock import InventoryLine, InventorySession, ProductBatch, StockBalance, StockMovement

__all__ = ["Base",
           "Role", "Permission", "RolePermission", "User", "AuditLog", "CompanySettings", "AppSetting",
           "Category", "Brand", "Unit", "Product", "ProductBarcode", "ProductPackaging",
           "PriceList", "ProductPrice", "ProductCostHistory",
           "StockMovement", "StockBalance", "InventorySession", "InventoryLine", "ProductBatch",
           "ReturnablePackaging", "DepositMovement",
           "Customer", "Sale", "SaleLine", "SaleReturn", "SaleReturnLine",
           "CustomerPayment", "PaymentAllocation", "CustomerCreditEvent",
           "Supplier", "PurchaseOrder", "PurchaseOrderLine", "GoodsReceipt", "GoodsReceiptLine",
           "SupplierInvoice", "SupplierPayment",
           "CustomerOrder", "CustomerOrderLine", "Delivery", "DeliveryLine", "CashSession",
           "CashMovement", "ExpenseCategory", "Expense", "BackupHistory",
           "DocumentSequence", "GeneratedDocument"]
