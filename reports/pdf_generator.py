"""
pdf_generator.py

Renders a RiskReport into a professional audit-style PDF using ReportLab.
Output looks like an actual IT audit deliverable — not a script printout.

Layout:
  - Cover page with risk rating and metadata
  - Executive summary
  - Risk flags (quick-reference)
  - Findings table (one section per finding)
  - Footer with generation timestamp and framework references
"""

import os
from datetime import datetime, timezone
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from api.risk_analyzer import RiskReport, RiskFinding


# ── Color Palette ─────────────────────────────────────────────────────────────

DARK_NAVY   = colors.HexColor("#0D1B2A")
MID_BLUE    = colors.HexColor("#1B4F72")
ACCENT_BLUE = colors.HexColor("#2E86C1")
LIGHT_GRAY  = colors.HexColor("#F2F3F4")
MID_GRAY    = colors.HexColor("#BFC9CA")
TEXT_DARK   = colors.HexColor("#1C2833")

RISK_COLORS = {
    "Critical":      colors.HexColor("#C0392B"),
    "High":          colors.HexColor("#E67E22"),
    "Medium":        colors.HexColor("#F1C40F"),
    "Low":           colors.HexColor("#27AE60"),
    "Informational": colors.HexColor("#2980B9"),
    "Unknown":       colors.HexColor("#95A5A6"),
}


def _risk_color(rating: str) -> colors.Color:
    return RISK_COLORS.get(rating, RISK_COLORS["Unknown"])


# ── Style Sheet ───────────────────────────────────────────────────────────────

def _build_styles():
    base = getSampleStyleSheet()

    styles = {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName="Helvetica-Bold",
            fontSize=26,
            textColor=colors.white,
            leading=32,
            alignment=TA_LEFT,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName="Helvetica",
            fontSize=11,
            textColor=colors.HexColor("#AEB6BF"),
            leading=16,
            alignment=TA_LEFT,
        ),
        "section_header": ParagraphStyle(
            "section_header",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=DARK_NAVY,
            spaceBefore=18,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=10,
            textColor=TEXT_DARK,
            leading=15,
            spaceAfter=6,
        ),
        "body_bold": ParagraphStyle(
            "body_bold",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=TEXT_DARK,
            leading=15,
        ),
        "finding_title": ParagraphStyle(
            "finding_title",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=DARK_NAVY,
            spaceBefore=14,
            spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=MID_BLUE,
            spaceAfter=2,
        ),
        "mono": ParagraphStyle(
            "mono",
            fontName="Courier",
            fontSize=8,
            textColor=TEXT_DARK,
            leading=12,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Helvetica",
            fontSize=8,
            textColor=MID_GRAY,
            alignment=TA_CENTER,
        ),
        "flag": ParagraphStyle(
            "flag",
            fontName="Helvetica",
            fontSize=10,
            textColor=TEXT_DARK,
            leading=14,
            leftIndent=12,
            spaceAfter=3,
        ),
    }
    return styles


# ── Cover Page ────────────────────────────────────────────────────────────────

def _cover_section(report: RiskReport, styles: dict) -> list:
    elements = []

    # Dark header block (simulated with a table)
    risk_color = _risk_color(report.overall_risk_rating)
    header_data = [[
        Paragraph("BLOCKCHAIN RISK ASSESSMENT REPORT", styles["cover_title"]),
    ]]
    header_table = Table(header_data, colWidths=[6.5 * inch])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 28),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 28),
        ("LEFTPADDING", (0, 0), (-1, -1), 20),
        ("RIGHTPADDING", (0, 0), (-1, -1), 20),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Risk rating badge
    badge_data = [[Paragraph(f"OVERALL RISK: {report.overall_risk_rating.upper()}  |  SCORE: {report.risk_score}/100", ParagraphStyle(
        "badge", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white, alignment=TA_CENTER
    ))]]
    badge_table = Table(badge_data, colWidths=[6.5 * inch])
    badge_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), risk_color),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(badge_table)
    elements.append(Spacer(1, 0.4 * inch))

    # Metadata table
    meta = [
        ["Wallet Address", report.wallet_address],
        ["Chain", report.chain],
        ["Transactions Analyzed", str(report.tx_count_analyzed)],
        ["Total Volume", f"{report.total_volume_native:.6f} {report.chain}"],
        ["Unique Counterparties", str(report.unique_counterparties)],
        ["Report Generated", report.generated_at[:19].replace("T", " ") + " UTC"],
        ["Frameworks Applied", "FATF · BSA · OFAC · COSO"],
    ]
    meta_table = Table(meta, colWidths=[2.2 * inch, 4.3 * inch])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), MID_BLUE),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, MID_GRAY),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(HRFlowable(width="100%", thickness=1, color=MID_GRAY))

    return elements


# ── Executive Summary ─────────────────────────────────────────────────────────

def _summary_section(report: RiskReport, styles: dict) -> list:
    elements = []
    elements.append(Paragraph("Executive Summary", styles["section_header"]))
    elements.append(Paragraph(report.analyst_note, styles["body"]))
    elements.append(Spacer(1, 0.15 * inch))

    if report.flags:
        elements.append(Paragraph("Risk Flags", styles["section_header"]))
        for flag in report.flags:
            elements.append(Paragraph(f"⚠  {flag}", styles["flag"]))
        elements.append(Spacer(1, 0.15 * inch))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    return elements


# ── Findings ──────────────────────────────────────────────────────────────────

def _finding_block(finding: RiskFinding, styles: dict) -> list:
    risk_color = _risk_color(finding.risk_rating)

    elements = []

    # Finding header row
    header_data = [[
        Paragraph(f"{finding.finding_id} — {finding.title}", ParagraphStyle(
            "fh", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white
        )),
        Paragraph(finding.risk_rating, ParagraphStyle(
            "fr", fontName="Helvetica-Bold", fontSize=10,
            textColor=colors.white, alignment=TA_RIGHT
        )),
    ]]
    header_table = Table(header_data, colWidths=[5 * inch, 1.5 * inch])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), risk_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 10),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(header_table)

    # Detail rows
    detail_data = [
        [Paragraph("Framework", styles["label"]),
         Paragraph(f"{finding.framework} — {finding.framework_ref}", styles["body"])],
        [Paragraph("Description", styles["label"]),
         Paragraph(finding.description, styles["body"])],
        [Paragraph("Evidence", styles["label"]),
         Paragraph(finding.evidence, styles["mono"])],
        [Paragraph("Recommendation", styles["label"]),
         Paragraph(finding.recommendation, styles["body"])],
    ]
    detail_table = Table(detail_data, colWidths=[1.4 * inch, 5.1 * inch])
    detail_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, MID_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
    ]))
    elements.append(detail_table)
    elements.append(Spacer(1, 0.2 * inch))

    return elements


def _findings_section(report: RiskReport, styles: dict) -> list:
    elements = []
    elements.append(Paragraph("Audit Findings", styles["section_header"]))
    elements.append(Spacer(1, 0.05 * inch))

    if not report.findings:
        elements.append(Paragraph("No findings identified.", styles["body"]))
        return elements

    for finding in report.findings:
        block = _finding_block(finding, styles)
        elements.append(KeepTogether(block))

    return elements


# ── Footer ────────────────────────────────────────────────────────────────────

def _footer_section(styles: dict) -> list:
    elements = [
        Spacer(1, 0.3 * inch),
        HRFlowable(width="100%", thickness=0.5, color=MID_GRAY),
        Spacer(1, 0.1 * inch),
        Paragraph(
            "This report was generated using AI-assisted analysis via the Anthropic Claude API. "
            "It is intended to supplement, not replace, professional compliance review. "
            "Framework references: FATF 40 Recommendations · Bank Secrecy Act (31 U.S.C. §5311) · "
            "OFAC SDN List · COSO 2013 Internal Control Framework.",
            styles["footer"]
        ),
    ]
    return elements


# ── Main Entry Point ──────────────────────────────────────────────────────────

def generate_pdf(report: RiskReport, output_path: str = None) -> bytes:
    """
    Generate a PDF audit report from a RiskReport.

    Args:
        report: Completed RiskReport from risk_analyzer.analyze_wallet()
        output_path: Optional file path to save PDF. If None, returns bytes only.

    Returns:
        PDF as bytes (also saves to output_path if provided)
    """
    buffer = BytesIO()
    styles = _build_styles()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    elements = []
    elements += _cover_section(report, styles)
    elements.append(Spacer(1, 0.25 * inch))
    elements += _summary_section(report, styles)
    elements.append(Spacer(1, 0.1 * inch))
    elements += _findings_section(report, styles)
    elements += _footer_section(styles)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes
