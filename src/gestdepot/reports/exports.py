"""Exports Excel (openpyxl) et PDF (ReportLab) — copies de consultation (§5.15).

Les exports ne modifient jamais la base.
"""
from __future__ import annotations

import os
from datetime import datetime

from ..config import app_paths
from ..domain.rules import format_xof


class ExportError(Exception):
    pass


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _export_path(name: str, suffix: str) -> str:
    directory = app_paths.exports_dir()
    os.makedirs(directory, exist_ok=True)
    return str(directory / f"{name}_{_timestamp()}.{suffix}")


def export_excel(title: str, headers: list[str], rows: list[list],
                 totals: dict[str, int] | None = None,
                 file_name: str | None = None) -> str:
    """Classeur formaté : en-têtes, filtres, formats monétaires, totaux, date."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover
        raise ExportError("openpyxl n'est pas installé.") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Rapport"

    sheet.append([title])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([f"Généré le {datetime.now():%d/%m/%Y %H:%M}"])
    sheet.append([])

    header_row = sheet.max_row + 1
    sheet.append(headers)
    fill = PatternFill("solid", fgColor="1F4E79")
    for column in range(1, len(headers) + 1):
        cell = sheet.cell(row=header_row, column=column)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        sheet.append(list(row))

    for column, header in enumerate(headers, start=1):
        letter = get_column_letter(column)
        width = max([len(str(header))] +
                    [len(str(row[column - 1])) for row in rows if len(row) >= column])
        sheet.column_dimensions[letter].width = min(max(width + 2, 10), 48)
        if any(token in header.lower() for token in ("montant", "total", "prix",
                                                    "valeur", "marge", "solde",
                                                    "encaisse", "dû")):
            for cell_row in range(header_row + 1, sheet.max_row + 1):
                sheet.cell(row=cell_row, column=column).number_format = '#,##0 "FCFA"'

    if totals:
        sheet.append([])
        for label, value in totals.items():
            sheet.append([label, value])
            cell = sheet.cell(row=sheet.max_row, column=2)
            cell.number_format = '#,##0 "FCFA"'
            cell.font = Font(bold=True)

    if rows:
        sheet.auto_filter.ref = (f"A{header_row}:"
                                 f"{get_column_letter(len(headers))}"
                                 f"{header_row + len(rows)}")

    path = _export_path(file_name or "rapport", "xlsx")
    workbook.save(path)
    return path


def export_pdf(title: str, headers: list[str], rows: list[list],
               period: str = "", company: dict | None = None,
               totals: dict[str, int] | None = None,
               file_name: str | None = None) -> str:
    """PDF : logo/coordonnées du dépôt, titre, période, tableau, totaux, pagination."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise ExportError("ReportLab n'est pas installé.") from exc

    path = _export_path(file_name or "rapport", "pdf")
    company = company or {}
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleFr", parent=styles["Title"], fontSize=15,
                                 spaceAfter=6)
    small = ParagraphStyle("SmallFr", parent=styles["Normal"], fontSize=8,
                           textColor=colors.grey)

    pagesize = landscape(A4) if len(headers) > 6 else A4
    doc = SimpleDocTemplate(path, pagesize=pagesize, title=title,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=18 * mm)

    story = []
    if company.get("name"):
        story.append(Paragraph(f"<b>{company['name']}</b>", styles["Heading2"]))
    contact_bits = [company.get("address"), company.get("phone")]
    contact = " — ".join(bit for bit in contact_bits if bit)
    if contact:
        story.append(Paragraph(contact, small))
    story.append(Spacer(1, 6))
    story.append(Paragraph(title, title_style))
    meta = f"Période : {period}" if period else ""
    meta += ("  |  " if meta else "") + f"Généré le {datetime.now():%d/%m/%Y %H:%M}"
    story.append(Paragraph(meta, small))
    story.append(Spacer(1, 10))

    data = [headers] + [[str(cell) for cell in row] for row in rows]
    if len(data) == 1:
        story.append(Paragraph("Aucune donnée sur la période.", styles["Normal"]))
    else:
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F2F2F2")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(table)

    if totals:
        story.append(Spacer(1, 10))
        for label, value in totals.items():
            story.append(Paragraph(f"<b>{label} :</b> {format_xof(value)}",
                                   styles["Normal"]))

    def _footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        footer = company.get("document_footer") or ""
        canvas.drawString(15 * mm, 10 * mm, footer[:110])
        canvas.drawRightString(pagesize[0] - 15 * mm, 10 * mm,
                               f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return path
