"""Degree certificate PDF with the APAAR printed and a QR that opens the verifier."""
from __future__ import annotations

import io

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..models import Credential
from . import sdjwt
from .service import DEFAULT_REVEAL, presentation_url


def render(c: Credential) -> bytes:
    claims = c.claims
    vp = sdjwt.present(c.sd_jwt, DEFAULT_REVEAL["DEGREE"])
    url = presentation_url(vp)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=4, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf_img = io.BytesIO()
    img.save(buf_img, format="PNG")
    buf_img.seek(0)

    out = io.BytesIO()
    W, H = landscape(A4)
    pdf = canvas.Canvas(out, pagesize=(W, H))
    pdf.setTitle(f"Degree certificate - {claims['name']}")
    navy = colors.HexColor("#1e3a5f")
    gold = colors.HexColor("#b08d3c")
    pdf.setStrokeColor(navy)
    pdf.setLineWidth(4)
    pdf.rect(12 * mm, 12 * mm, W - 24 * mm, H - 24 * mm)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.2)
    pdf.rect(16 * mm, 16 * mm, W - 32 * mm, H - 32 * mm)

    pdf.setFillColor(navy)
    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawCentredString(W / 2, H - 42 * mm, claims["university"])
    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#555555"))
    pdf.drawCentredString(W / 2, H - 50 * mm, "SIMULATED UNIVERSITY - DEMO CERTIFICATE (APAAR Registry prototype)")

    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Oblique", 14)
    pdf.drawCentredString(W / 2, H - 68 * mm, "This is to certify that")
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawCentredString(W / 2, H - 82 * mm, claims["name"])
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(W / 2, H - 91 * mm, f"APAAR ID: {claims.get('apaar_id') or '-'}")
    pdf.setFont("Helvetica-Oblique", 14)
    pdf.drawCentredString(W / 2, H - 105 * mm, "having fulfilled the requirements, has been awarded the degree of")
    pdf.setFont("Helvetica-Bold", 18)
    spec = claims.get("specialisation")
    pdf.drawCentredString(W / 2, H - 118 * mm, f"{claims['degree']} in {spec}" if spec else claims["degree"])
    pdf.setFont("Helvetica", 13)
    cg = f" (CGPA {claims['cgpa']})" if claims.get("cgpa") is not None else ""
    pdf.drawCentredString(W / 2, H - 128 * mm, f"with {claims['class_awarded']}{cg}, in the year {claims['year_of_award']}")
    pdf.drawCentredString(W / 2, H - 137 * mm, f"Studied at {claims['institution']}")

    pdf.drawImage(ImageReader(buf_img), W - 75 * mm, 22 * mm, 50 * mm, 50 * mm)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(W - 50 * mm, 19 * mm, "Scan to verify (works offline)")
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#444444"))
    pdf.drawString(24 * mm, 30 * mm, f"Credential: {c.id}")
    pdf.drawString(24 * mm, 25 * mm, f"Signed by issuer key {c.issuer_kid} (Ed25519, SD-JWT). Revocation: W3C Bitstring Status List.")
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(navy)
    pdf.drawString(24 * mm, 40 * mm, "Registrar")
    pdf.showPage()
    pdf.save()
    return out.getvalue()
