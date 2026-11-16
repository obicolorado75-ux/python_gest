"""Tickets et documents imprimables (§5.5, §9).

L'impression ne doit jamais bloquer une vente : le ticket est d'abord produit
sous forme de fichier HTML (58/80 mm) que l'utilisateur peut imprimer, et
l'absence d'imprimante n'est pas une erreur (aucune imprimante supposée).
"""
from __future__ import annotations

import html
import os
from datetime import datetime

from ..config import app_paths
from ..domain.rules import format_xof, label_payment, label_status


class PrintError(Exception):
    pass


def _documents_dir():
    directory = app_paths.data_dir() / "documents"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


TICKET_CSS = """
@page { size: 80mm auto; margin: 4mm; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 11px;
       color: #111; width: 72mm; }
h1 { font-size: 14px; margin: 0 0 2mm; text-align: center; }
.center { text-align: center; }
.muted { color: #555; }
table { width: 100%; border-collapse: collapse; }
td { padding: 1mm 0; vertical-align: top; }
td.qty { text-align: center; }
td.amount { text-align: right; white-space: nowrap; }
hr { border: none; border-top: 1px dashed #888; margin: 2mm 0; }
.total { font-size: 13px; font-weight: bold; }
.footer { margin-top: 3mm; text-align: center; font-size: 9px; color: #555; }
"""


def sale_receipt_html(sale, company: dict | None = None,
                      lines: list | None = None) -> str:
    """Ticket de caisse 80 mm pour une vente confirmée (§5.5)."""
    company = company or {}
    # la relation peut être déchargée sur un objet détaché : repli sur le comptoir
    try:
        customer_name = sale.customer.name if sale.customer else "Comptoir"
    except Exception:
        customer_name = "Comptoir"
    rows = []
    for line in (lines if lines is not None else []):
        rows.append(
            f"<tr><td>{_esc(line.designation)}<br>"
            f"<span class='muted'>{_esc(line.unit_label)}</span></td>"
            f"<td class='qty'>{line.quantity_display or line.quantity}</td>"
            f"<td class='amount'>{format_xof(line.total)}</td></tr>")
    deposit = ""
    if getattr(sale, "deposit_amount", 0):
        deposit = (f"<tr><td>Dont consigne</td>"
                   f"<td></td><td class='amount'>{format_xof(sale.deposit_amount)}"
                   f"</td></tr>")
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Ticket {_esc(sale.number)}</title><style>{TICKET_CSS}</style></head>
<body>
<h1>{_esc(company.get('name') or 'GestDepot')}</h1>
<div class="center muted">
  {_esc(company.get('address') or '')}<br>
  {_esc(company.get('phone') or '')}
</div>
<hr>
<div><b>Ticket n° {_esc(sale.number)}</b></div>
<div class="muted">{datetime.now():%d/%m/%Y %H:%M}</div>
<div class="muted">Client : {_esc(customer_name)}</div>
<hr>
<table>{"".join(rows)}</table>
<hr>
<table>
  <tr><td class="total">Total à payer</td>
      <td></td><td class="amount total">{format_xof(sale.total_amount)}</td></tr>
  {deposit}
  <tr><td>Encaissé</td><td></td>
      <td class="amount">{format_xof(sale.paid_amount)}</td></tr>
  <tr><td>Reste dû</td><td></td>
      <td class="amount">{format_xof(sale.total_amount - sale.paid_amount)}</td></tr>
</table>
<hr>
<div>Paiement : {_esc(label_payment(sale.payment_method))}</div>
<div class="muted">Statut : {_esc(label_status(sale.status))}</div>
<div class="footer">{_esc(company.get('document_footer') or '')}<br>
Merci de votre visite — GestDepot (hors ligne)</div>
</body></html>"""


def write_receipt(sale, company: dict | None = None, lines: list | None = None,
                  open_after: bool = False) -> str:
    """Écrit le ticket dans le dossier documents et retourne son chemin."""
    path = str(_documents_dir() / f"ticket_{sale.number}.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(sale_receipt_html(sale, company, lines))
    if open_after:
        import webbrowser
        try:  # ouvre le visualiseur du système pour lancer l'impression
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception:  # pragma: no cover - dépend du poste
            pass
    return path


DOCUMENT_CSS = """
@page { size: A4; margin: 14mm; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 11px; color: #111; }
h1 { font-size: 17px; margin: 0 0 1mm; }
h2 { font-size: 13px; margin: 4mm 0 1mm; }
.muted { color: #555; }
.head { display: flex; justify-content: space-between; margin-bottom: 4mm; }
table { width: 100%; border-collapse: collapse; margin-top: 2mm; }
th, td { border-bottom: 1px solid #ccc; padding: 1.5mm 1mm; text-align: left; }
td.amount, th.amount { text-align: right; white-space: nowrap; }
td.qty, th.qty { text-align: center; }
.signature { margin-top: 12mm; display: flex; justify-content: space-between; }
.signature div { width: 45%; border-top: 1px solid #888; padding-top: 2mm; }
.footer { margin-top: 8mm; font-size: 9px; color: #555; text-align: center; }
"""


def delivery_note_html(delivery: dict, company: dict | None = None) -> str:
    """Bon de livraison A4 (§5.10) — imprimable sans imprimante supposée.

    ``delivery`` est le dictionnaire retourné par ``DeliveryService.get_delivery``.
    """
    company = company or {}
    rows = []
    for line in delivery.get("lines", []):
        quantity = line.get("delivered_qty") or line.get("prepared_qty") or 0
        unit_price = line.get("unit_price") or 0
        rows.append(
            f"<tr><td>{_esc(line.get('designation'))}</td>"
            f"<td>{_esc(line.get('unit_label'))}</td>"
            f"<td class='qty'>{quantity}</td>"
            f"<td class='amount'>{format_xof(unit_price * quantity)}</td></tr>")
    total = sum((line.get("delivered_qty") or line.get("prepared_qty") or 0)
                * (line.get("unit_price") or 0)
                for line in delivery.get("lines", []))
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Bon de livraison {_esc(delivery.get('number'))}</title>
<style>{DOCUMENT_CSS}</style></head>
<body>
<div class="head">
  <div><h1>{_esc(company.get('name') or 'GestDepot')}</h1>
    <div class="muted">{_esc(company.get('address') or '')}<br>
    {_esc(company.get('phone') or '')}</div></div>
  <div class="muted">
    <b>Bon de livraison</b><br>
    N° {_esc(delivery.get('number'))}<br>
    Date : {datetime.now():%d/%m/%Y}<br>
    Commande : {_esc(delivery.get('order_number') or '—')}
  </div>
</div>
<h2>Client</h2>
<div>{_esc(delivery.get('customer'))}</div>
<div class="muted">{_esc(delivery.get('address') or '')}</div>
<h2>Marchandise</h2>
<table>
  <thead><tr><th>Désignation</th><th>Conditionnement</th>
  <th class="qty">Quantité</th><th class="amount">Montant</th></tr></thead>
  <tbody>{"".join(rows) or '<tr><td colspan="4">Aucune ligne</td></tr>'}</tbody>
</table>
<table>
  <tr><td>Total marchandise</td><td class="amount">{format_xof(total)}</td></tr>
  <tr><td>Frais de livraison</td>
      <td class="amount">{format_xof(delivery.get('fee') or 0)}</td></tr>
  <tr><td><b>Total</b></td>
      <td class="amount"><b>{format_xof(total + (delivery.get('fee') or 0))}</b></td></tr>
  <tr><td>Encaissé à la livraison</td>
      <td class="amount">{format_xof(delivery.get('collected_amount') or 0)}</td></tr>
</table>
<div class="muted">Livreur : {_esc(delivery.get('driver') or '—')}
  · Véhicule : {_esc(delivery.get('vehicle') or '—')}</div>
<div class="muted">Statut : {_esc(delivery.get('status_label') or '')}
  {_esc(delivery.get('proof') or '')}</div>
<div class="signature">
  <div>Signature du livreur</div><div>Signature et cachet du client</div>
</div>
<div class="footer">{_esc(company.get('document_footer') or '')}<br>
GestDepot — document généré hors ligne</div>
</body></html>"""


def write_document(name: str, content: str, open_after: bool = False) -> str:
    """Écrit un document HTML dans le dossier documents et retourne son chemin."""
    path = str(_documents_dir() / f"{name}.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    if open_after:
        import webbrowser
        try:  # pragma: no cover - dépend du poste
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception:
            pass
    return path
