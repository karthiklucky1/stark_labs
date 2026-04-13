"""
Stark Labs — Iron Legion Micro-Modules
Each function is a hyper-specialized, single-purpose AI unit.
All modules share the same signature: async (input: str) -> str

Available modules
─────────────────
  PDF Reader        — extract raw text from a PDF file path
  Extraction        — pull named entities (people, orgs, amounts) from text
  Translation       — translate non-English financial text → English
  Invoice Parser    — convert English invoice text → structured JSON
  JSON Formatting   — generic text → JSON object coercion
  Payment           — execute payment from a structured JSON invoice payload
"""
import os
import sys
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from stark_logger import log

load_dotenv(Path(__file__).parent.parent / ".env")
client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ─────────────────────────────────────────────
# Module: PDF Reader
# ─────────────────────────────────────────────

async def module_pdf_reader(input_text: str) -> str:
    """
    Input : absolute path to a PDF file (as a string)
    Output: raw extracted text from the PDF
    Uses PyMuPDF — no LLM call, pure local extraction.
    """
    import fitz  # PyMuPDF
    pdf_path = input_text.strip()
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text())
    doc.close()

    extracted = "\n".join(pages_text).strip()
    log("module_run", module="PDF Reader", chars_extracted=len(extracted))
    return extracted


# ─────────────────────────────────────────────
# Module: Extraction
# ─────────────────────────────────────────────

async def module_extraction(input_text: str) -> str:
    """Extract named entities: people, companies, monetary amounts, dates."""
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Module: Extraction. Extract ALL named entities from the text.\n"
                    "Output a JSON object with these keys:\n"
                    "  people: list of person names\n"
                    "  companies: list of company/organization names\n"
                    "  amounts: list of monetary amounts (keep currency symbols)\n"
                    "  dates: list of dates found\n"
                    "Output ONLY the JSON object. Nothing else."
                ),
            },
            {"role": "user", "content": input_text},
        ],
    )
    result = resp.choices[0].message.content
    log("module_run", module="Extraction", tokens=resp.usage.total_tokens)
    return result


# ─────────────────────────────────────────────
# Module: Translation
# ─────────────────────────────────────────────

async def module_translation(input_text: str) -> str:
    """Translate financial/invoice text from any language → English."""
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Module: Translation — a specialist in financial document translation.\n"
                    "Translate the provided text into English.\n"
                    "Preserve all numbers, amounts, dates, and proper nouns exactly.\n"
                    "Output ONLY the translated English text. No notes, no explanation."
                ),
            },
            {"role": "user", "content": input_text},
        ],
    )
    result = resp.choices[0].message.content
    log("module_run", module="Translation", tokens=resp.usage.total_tokens)
    return result


# ─────────────────────────────────────────────
# Module: Invoice Parser
# ─────────────────────────────────────────────

async def module_invoice_parser(input_text: str) -> str:
    """
    Parse English invoice text → structured JSON.
    Output: { vendor, invoice_number, date, line_items, subtotal, tax, total, currency }
    """
    resp = await client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Module: Invoice Parser — an expert financial document analyst.\n"
                    "Parse the invoice text and output a JSON object with these keys:\n"
                    "  vendor: string (company or person issuing the invoice)\n"
                    "  invoice_number: string\n"
                    "  date: string (ISO format if possible)\n"
                    "  line_items: list of {description, quantity, unit_price, total}\n"
                    "  subtotal: number\n"
                    "  tax: number\n"
                    "  total: number\n"
                    "  currency: string (3-letter code, e.g. USD, JPY, EUR)\n"
                    "If a field is not found, use null. Output ONLY the JSON object."
                ),
            },
            {"role": "user", "content": input_text},
        ],
    )
    result = resp.choices[0].message.content
    log("module_run", module="Invoice Parser", tokens=resp.usage.total_tokens)
    return result


# ─────────────────────────────────────────────
# Module: JSON Formatting (generic fallback)
# ─────────────────────────────────────────────

async def module_json_formatting(input_text: str) -> str:
    """Generic: coerce any text into a JSON object with key 'data'."""
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Module: JSON Formatting.\n"
                    "Convert the provided text into a clean JSON object.\n"
                    "Use the key 'data' if no better structure is apparent.\n"
                    "Output ONLY the JSON object."
                ),
            },
            {"role": "user", "content": input_text},
        ],
    )
    result = resp.choices[0].message.content
    log("module_run", module="JSON Formatting", tokens=resp.usage.total_tokens)
    return result


# ─────────────────────────────────────────────
# Module: Payment
# ─────────────────────────────────────────────

async def module_payment(input_text: str) -> str:
    """
    Input : JSON string from Invoice Parser
    Output: payment confirmation JSON

    Uses Stripe if STRIPE_SECRET_KEY is set, otherwise simulates.
    """
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")

    try:
        invoice = json.loads(input_text)
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "reason": "Invalid JSON from previous module"})

    total = invoice.get("total")
    currency = (invoice.get("currency") or "USD").lower()
    vendor = invoice.get("vendor", "Unknown Vendor")

    if total is None:
        return json.dumps({"status": "error", "reason": "No total found in invoice"})

    amount_cents = int(total * 100)

    if stripe_key:
        try:
            import stripe  # pip install stripe
        except ImportError:
            stripe_key = None  # fall through to simulation

    if stripe_key:
        stripe.api_key = stripe_key  # type: ignore[reportPossiblyUnbound]
        charge = stripe.PaymentIntent.create(  # type: ignore[reportPossiblyUnbound]
            amount=amount_cents,
            currency=currency,
            description=f"Invoice payment to {vendor}",
            confirm=False,
        )
        result = {
            "status": "payment_intent_created",
            "payment_intent_id": charge.id,
            "amount": total,
            "currency": currency,
            "vendor": vendor,
        }
    else:
        # Simulation mode — no real charge
        result = {
            "status": "simulated_payment",
            "amount": total,
            "currency": currency,
            "vendor": vendor,
            "note": "Set STRIPE_SECRET_KEY in .env to execute real payments",
        }

    log("module_run", module="Payment", status=result["status"], amount=total, currency=currency)
    return json.dumps(result, indent=2)


# ─────────────────────────────────────────────
# Registry — JARVIS picks from this
# ─────────────────────────────────────────────

AVAILABLE_MODULES: dict[str, callable] = {
    "PDF Reader": module_pdf_reader,
    "Extraction": module_extraction,
    "Translation": module_translation,
    "Invoice Parser": module_invoice_parser,
    "JSON Formatting": module_json_formatting,
    "Payment": module_payment,
}
