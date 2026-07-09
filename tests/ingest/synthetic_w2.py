"""Generate a SYNTHETIC W-2 — fake SSN (123-45-6789), fake employer.

No personal documents are ever committed. This builds a throwaway W-2 (both a
text rendering and, when reportlab is available, a PDF) purely from fake data,
for the ingestion tests. Numbers cross-foot: Box 4 = 6.2% of Box 3, Box 6 =
1.45% of Box 5.
"""

from __future__ import annotations

from decimal import Decimal

FAKE_SSN = "123-45-6789"
FAKE_EIN = "12-3456789"
FAKE_EMPLOYER = "Acme Synthetic Widgets LLC"
FAKE_ACCOUNT = "000111222333"

BOX1_WAGES = Decimal("50000.00")
BOX2_FIT = Decimal("8000.00")
BOX3_SS_WAGES = Decimal("52000.00")
BOX4_SS_TAX = (BOX3_SS_WAGES * Decimal("0.062")).quantize(Decimal("0.01"))  # 3224.00
BOX5_MEDICARE_WAGES = Decimal("52000.00")
BOX6_MEDICARE_TAX = (BOX5_MEDICARE_WAGES * Decimal("0.0145")).quantize(Decimal("0.01"))  # 754.00


def synthetic_w2_text(*, tampered: bool = False) -> str:
    """Text rendering of the synthetic W-2 (the redaction/extraction source).

    ``tampered=True`` makes Box 4 disagree with 6.2% of Box 3, to exercise the
    cross-foot failure path.
    """
    box4 = Decimal("9999.00") if tampered else BOX4_SS_TAX
    return "\n".join(
        [
            "Form W-2 Wage and Tax Statement 2025",
            f"a Employee's social security number {FAKE_SSN}",
            f"b Employer identification number (EIN) {FAKE_EIN}",
            f"c Employer name {FAKE_EMPLOYER}",
            f"Account number: {FAKE_ACCOUNT}",
            f"1 Wages, tips, other compensation {BOX1_WAGES}",
            f"2 Federal income tax withheld {BOX2_FIT}",
            f"3 Social security wages {BOX3_SS_WAGES}",
            f"4 Social security tax withheld {box4}",
            f"5 Medicare wages and tips {BOX5_MEDICARE_WAGES}",
            f"6 Medicare tax withheld {BOX6_MEDICARE_TAX}",
        ]
    )


def synthetic_w2_pdf(*, tampered: bool = False) -> bytes:
    """Render the synthetic W-2 to a one-page PDF using reportlab."""
    import io

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for line in synthetic_w2_text(tampered=tampered).splitlines():
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()
