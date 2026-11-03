"""
Live Production AI OCR Pipeline gamit ang OCR.space free tier.

Kailangan ng env var na OCR_SPACE_API_KEY (.env locally, Render env sa production).
Kailangan din ng "httpx" package.

UPDATED (OCR matching fix):
  1. Confusable mapping — pinag-iisa ang mga karakter na madalas
     mapagkamalan ng OCR (O/0, I/L/1, S/5, B/8, Z/2, G/6) sa BOTH
     panig ng paghahambing, kaya hindi na nagfa-fail kung "O" ang nabasa
     pero "0" ang nasa reference.
  2. Retry — kung hindi nag-match ang OCREngine 2, susubukan ulit
     gamit ang OCREngine 1 (iba ang paraan ng pagbasa, minsan mas
     tama sa mga numero).
  3. Near-match — pinapayagan ang MAXIMUM NA 1 maling karakter para sa
     reference na 10+ characters (isang digit na nagkamali ang OCR).
     Ang mas maikli ay kailangang eksakto.
  4. Log — nagpi-print ng nabasa ng OCR (sa Render logs) para
     madaling malaman kung bakit nag-fail.
"""
import os
import re
from typing import List, Optional

import httpx

OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/image"

# Ilang maling karakter ang papayagan sa near-match, at mula ilang
# characters ang reference bago payagan ito.
MAX_MISMATCHES = 1
MIN_LENGTH_FOR_NEAR_MATCH = 10

_AMOUNT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:PHP|₱|P)\s?([\d,]+\.\d{2})", re.IGNORECASE
)

# Mga karakter na madalas mapagkamalan ng OCR — pinag-iisa sa isang
# canonical na anyo.
_CONFUSABLE = str.maketrans({
    "O": "0", "Q": "0", "D": "0",
    "I": "1", "L": "1",
    "S": "5",
    "B": "8",
    "Z": "2",
    "G": "6",
})


def _get_api_key() -> str:
    key = os.environ.get("OCR_SPACE_API_KEY")
    if not key:
        raise RuntimeError("OCR_SPACE_API_KEY is not set.")
    return key


def _normalize(text: str) -> str:
    """
    Alisin ang spaces, dashes, atbp. at pag-isahin ang mga karakter na
    madalas mapagkamalan ng OCR, para tumugma kahit naka-group ang ref
    no. o mali ang basa ng ilang karakter.
    """
    cleaned = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    return cleaned.translate(_CONFUSABLE)


def _contains_with_tolerance(haystack: str, needle: str, max_mismatches: int) -> bool:
    """
    True kung ang `needle` ay lumalabas sa `haystack` na may hanggang
    `max_mismatches` na maling karakter (pareho ang haba — walang
    insert/delete, para hindi lumuwag nang sobra). Naka-normalize na
    ang parehong input.
    """
    if not needle:
        return False
    if needle in haystack:
        return True
    if max_mismatches <= 0 or len(needle) < MIN_LENGTH_FOR_NEAR_MATCH:
        return False

    n = len(needle)
    for start in range(0, len(haystack) - n + 1):
        window = haystack[start:start + n]
        mismatches = 0
        for a, b in zip(window, needle):
            if a != b:
                mismatches += 1
                if mismatches > max_mismatches:
                    break
        if mismatches <= max_mismatches:
            return True
    return False


async def extract_text_from_receipt(image_url: str, engine: str = "2") -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OCR_SPACE_ENDPOINT,
                data={
                    "apikey": _get_api_key(),
                    "url": image_url,
                    "OCREngine": engine,
                    "scale": "true",
                    "detectOrientation": "true",
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


def _reference_matches(reference_number: str, lines: List[str]) -> bool:
    ref = _normalize(reference_number or "")
    if not ref:
        return False
    text = _normalize("\n".join(lines))
    return _contains_with_tolerance(text, ref, MAX_MISMATCHES)


async def verify_payment_receipt(image_url: str, reference_number: str) -> dict:
    lines: List[str] = []
    matched = False
    last_error: Optional[Exception] = None

    # Engine 2 muna; kung hindi nag-match, subukan ang Engine 1.
    for engine in ("2", "1"):
        try:
            lines = await extract_text_from_receipt(image_url, engine=engine)
        except RuntimeError as exc:
            last_error = exc
            print(f"[OCR] engine={engine} failed: {exc}")
            continue

        matched = _reference_matches(reference_number, lines)
        print(
            f"[OCR] engine={engine} matched={matched} "
            f"ref={reference_number!r} lines={lines[:25]!r}"
        )
        if matched:
            break

    # Kung parehong engine ay nag-error (hindi lang "walang tugma"),
    # ipaalam bilang error para 503 ang lumabas at hindi "Fraud Alert".
    if not lines and last_error is not None and not matched:
        raise last_error

    return {
        "matched": matched,
        "extracted_amount": _extract_amount_from_lines(lines),
        "raw_lines": lines,
    }