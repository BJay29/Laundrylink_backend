"""
NEW (Secure Payment Verification System) — Live Production AI OCR
Pipeline gamit ang OCR.space free tier (25,000 scans/month).

Ang OCR_SPACE_API_KEY ay dapat talaga naka-set bilang environment
variable sa Render (Settings > Environment). Ang value sa ibaba
("K82062009788957") ay FALLBACK lang — gagamitin kung wala pang
na-set na env var, para gumana agad habang nagte-test lokal. Sa
production, siguraduhing may nakaset na OCR_SPACE_API_KEY sa Render
mismo, sa halip na umasa sa hardcoded fallback na ito.

Kailangan din ng "httpx" package. Kung wala pa ito naka-install:
    pip install httpx --break-system-packages
"""
import os
import re
from typing import List, Optional

import httpx

# NOTE: palitan/i-set ang OCR_SPACE_API_KEY bilang env var sa Render.
# Ang default value dito ay ang ibinigay na key — gumagana ito kaagad
# kahit wala pang env var, pero dapat pa ring i-configure nang tama sa
# production environment settings.
OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY", "K82062009788957")
OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/imageurl"

# Sinusubukang hanapin ang halaga sa resibo (hal. "PHP 410.00",
# "₱1,250.50", "P 300.00") — maluwag na pattern dahil iba-ibang paraan
# ng pag-print ng amount ang bawat app (GCash, Maya, bank transfer).
_AMOUNT_PATTERN = re.compile(r"(?:PHP|₱|P)\s?([\d,]+\.\d{2})", re.IGNORECASE)


async def extract_text_from_receipt(image_url: str) -> List[str]:
    """
    Nagpapadala ng public image URL (mula sa Supabase Storage) papunta
    sa OCR.space, at ibinabalik ang extracted text bilang listahan ng
    linya (isang linya bawat entry sa ParsedText).

    Raises RuntimeError kung nag-fail ang OCR processing mismo (hal.
    hindi mabasa ang larawan), o httpx.HTTPStatusError kung nag-fail
    ang network request papunta sa OCR.space.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            OCR_SPACE_ENDPOINT,
            params={
                "apikey": OCR_SPACE_API_KEY,
                "url": image_url,
                "OCREngine": 2,  # mas mataas na accuracy engine
            },
        )
    response.raise_for_status()
    data = response.json()

    if data.get("IsErroredOnProcessing"):
        error_messages = data.get("ErrorMessage") or ["OCR processing failed."]
        raise RuntimeError(
            error_messages[0] if isinstance(error_messages, list) else str(error_messages)
        )

    lines: List[str] = []
    for result in data.get("ParsedResults") or []:
        text = result.get("ParsedText") or ""
        lines.extend(line for line in text.splitlines() if line.strip())
    return lines


def _extract_amount_from_lines(lines: List[str]) -> Optional[float]:
    """Sinusubukang hanapin ang unang amount-like na pattern sa resibo."""
    for line in lines:
        match = _AMOUNT_PATTERN.search(line)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


async def verify_payment_receipt(image_url: str, reference_number: str) -> dict:
    """
    Buong OCR verification workflow para sa isang resibo:
      1. Kunin ang extracted text mula sa larawan.
      2. STRICT SUBSTRING MATCHING — dapat literal na lumabas ang
         reference_number sa loob ng extracted text (case-insensitive).
      3. Subukang kunin din ang amount na nakalagay sa resibo, para sa
         cross-check ng staff laban sa final_price (hindi kinakailangan
         na tumugma — nakadepende pa rin sa desisyon ng staff kapag
         nag-a-approve, pero available bilang karagdagang signal).

    Nagbabalik ng {"matched": bool, "extracted_amount": float | None,
    "raw_lines": list[str]}. Ang "raw_lines" ay para sa debugging/audit
    lang, hindi kailangang i-save sa DB.
    """
    lines = await extract_text_from_receipt(image_url)
    joined_text = "\n".join(lines).upper()
    matched = reference_number.strip().upper() in joined_text
    extracted_amount = _extract_amount_from_lines(lines)

    return {
        "matched": matched,
        "extracted_amount": extracted_amount,
        "raw_lines": lines,
    }