"""
Live Production AI OCR Pipeline gamit ang OCR.space free tier.

Kailangan ng env var na OCR_SPACE_API_KEY (.env locally, Render env sa production).
Kailangan din ng "httpx" package.
"""
import os
import re
from typing import List, Optional

import httpx

OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/image"

_AMOUNT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:PHP|₱|P)\s?([\d,]+\.\d{2})", re.IGNORECASE
)


def _get_api_key() -> str:
    key = os.environ.get("OCR_SPACE_API_KEY")
    if not key:
        raise RuntimeError("OCR_SPACE_API_KEY is not set.")
    return key


def _normalize(text: str) -> str:
    """Alisin ang spaces, dashes, atbp. para tumugma kahit naka-group ang ref no."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


async def extract_text_from_receipt(image_url: str) -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OCR_SPACE_ENDPOINT,
                data={
                    "apikey": _get_api_key(),
                    "url": image_url,
                    "OCREngine": "2",
                },
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Huwag isama ang buong request/URL sa mensahe
        raise RuntimeError(f"OCR service error (HTTP {exc.response.status_code}).") from None
    except httpx.RequestError:
        raise RuntimeError("Hindi maabot ang OCR service (timeout o network error).") from None

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
    for line in lines:
        match = _AMOUNT_PATTERN.search(line)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


async def verify_payment_receipt(image_url: str, reference_number: str) -> dict:
    lines = await extract_text_from_receipt(image_url)

    ref = _normalize(reference_number or "")
    matched = bool(ref) and ref in _normalize("\n".join(lines))

    return {
        "matched": matched,
        "extracted_amount": _extract_amount_from_lines(lines),
        "raw_lines": lines,
    }