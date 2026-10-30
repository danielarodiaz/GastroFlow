from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from gastroflow.config.settings import Settings, get_settings


AZURE_API_VERSION = "2024-11-30"


@dataclass(frozen=True)
class ExtractedExpenseItem:
    motivo: str
    cantidad: Decimal
    unidad: str
    subtotal: Decimal
    marca: str | None = None
    descripcion: str | None = None
    confianza: Decimal | None = None

    @property
    def precio_unitario(self) -> Decimal:
        return (self.subtotal / self.cantidad).quantize(Decimal("0.01"))


@dataclass
class ExpenseDocumentDraft:
    fecha: date | None = None
    lugar: str = ""
    monto_total: Decimal | None = None
    medio_pago: str | None = None
    destinatario_pago: str | None = None
    identificador_pago: str | None = None
    comentario: str | None = None
    items: list[ExtractedExpenseItem] = field(default_factory=list)
    qr_contenido: str | None = None
    texto_extraido: str = ""
    motor_lectura: str = ""
    confianza: Decimal | None = None
    advertencias: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        data = asdict(self)
        # The original document remains the evidence. Avoid duplicating account,
        # tax or banking identifiers from raw OCR/QR text in structured storage.
        data.pop("texto_extraido", None)
        data.pop("qr_contenido", None)
        return json.dumps(data, ensure_ascii=False, default=str)


class DocumentReader(Protocol):
    def analyze(self, content: bytes, content_type: str) -> ExpenseDocumentDraft: ...


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _money(value: str) -> Decimal:
    clean = re.sub(r"[^0-9.,]", "", value.replace("O", "0").replace("o", "0"))
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif clean.count(".") == 1 and len(clean.rsplit(".", 1)[1]) == 3:
        clean = clean.replace(".", "")
    return Decimal(clean).quantize(Decimal("0.01"))


KNOWN_PLACE_BY_CUIT = {
    "30673770483": "Distribuidora VIDT",
}

KNOWN_BRANDS = {
    "BLATI": "Blati",
    "LAS MAJADAS": "Las Majadas",
    "D-70": "D-70",
}


def _split_known_brand(description: str) -> tuple[str, str | None]:
    for token, display in KNOWN_BRANDS.items():
        if token in description.upper():
            motive = re.sub(re.escape(token), "", description, flags=re.I)
            return _clean(motive).strip("-_. "), display
    return description, None


def _thermal_ticket_items(text: str) -> list[ExtractedExpenseItem]:
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    quantity_pattern = re.compile(
        r"^[^\d]{0,3}(?P<qty>\d+(?:[.,]\d{1,3})?)\s*[xX]\s*\$?\s*"
        r"(?P<unit_price>\d[\d.,]*)"
    )
    amount_pattern = re.compile(
        r"^(?P<description>.+?)\s+\$?\s*(?P<amount>\d[\d.,]*)\D*$", re.I
    )
    summary_words = ("TOTAL", "IVA", "MERCADO PAGO", "TRANSPARENCIA", "CANTIDAD DE ITEMS")
    items: list[ExtractedExpenseItem] = []
    for index, line in enumerate(lines):
        normalized_line = re.sub(r"([xX])\s*[5S]\s+(?=\d)", r"\1 $ ", line)
        quantity_match = quantity_pattern.search(normalized_line)
        if not quantity_match:
            continue
        quantity = Decimal(quantity_match.group("qty").replace(",", "."))
        description_parts: list[str] = []
        subtotal: Decimal | None = None
        for candidate in lines[index + 1:index + 4]:
            upper_candidate = candidate.upper()
            if quantity_pattern.search(candidate) or any(word in upper_candidate for word in summary_words):
                break
            if upper_candidate.startswith(("DES ", "DESC ", "DESCUENTO")):
                continue
            amount_match = amount_pattern.match(candidate)
            if amount_match:
                description_parts.append(amount_match.group("description"))
                try:
                    subtotal = _money(amount_match.group("amount"))
                except Exception:
                    subtotal = None
                break
            description_parts.append(candidate)
        if subtotal is None or not description_parts:
            continue
        original_description = _clean(" ".join(description_parts)).strip("-_. ")
        motive = re.sub(
            r"\s+(?:X\s*)?\d+(?:[.,]\d+)?\s*(?:KG|GR|G|L|LT|ML|HORMA|UNIDAD)\s*$",
            "",
            original_description,
            flags=re.I,
        ).strip("-_. ")
        motive, brand = _split_known_brand(motive)
        upper_description = original_description.upper()
        if re.search(r"\bKG\b", upper_description) or quantity != quantity.to_integral_value():
            unit = "KG"
        elif "HORMA" in upper_description:
            unit = "HORMA"
        else:
            unit = "UNIDAD"
        items.append(
            ExtractedExpenseItem(
                motivo=motive.title(),
                cantidad=quantity,
                unidad=unit,
                subtotal=subtotal,
                marca=brand,
                descripcion=original_description,
                confianza=Decimal("0.75"),
            )
        )
    return items


def _ticket_date(text: str) -> date | None:
    labeled = re.search(r"\bFECHA\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text, re.I)
    candidates = [labeled.group(1)] if labeled else re.findall(
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text
    )
    for raw in candidates:
        normalized = raw.replace("-", "/")
        day, month, year = normalized.split("/")
        if len(year) == 2:
            year = f"20{year}"
        if int(year) < 2020:
            continue
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            continue
    return None


def _ticket_place(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    for cuit, place in KNOWN_PLACE_BY_CUIT.items():
        if cuit in digits:
            return place
    for line in text.splitlines():
        clean = _clean(line).strip("0123456789 .-_")
        if "DISTRIBUIDORA" in clean.upper():
            return clean.title()
    return ""


def _ticket_total(text: str) -> Decimal | None:
    patterns = (
        r"MERCADO\s+PAGO[^\n]*?([0-9]{2,}[\d.,]*)\D*$",
        r"\bTOTAL[^\n]*?([0-9]{2,}[\d.,]*)\D*$",
    )
    for pattern in patterns:
        matches = re.findall(pattern, text, re.I | re.M)
        for value in reversed(matches):
            try:
                return _money(value)
            except Exception:
                continue
    return None


def parse_purchase_comment(comment: str) -> list[ExtractedExpenseItem]:
    """Parse simple Spanish purchase notes, always as a reviewable proposal."""
    normalized = _clean(comment)
    segments = re.split(r"\s+(?:y|,|\+)\s+", normalized, flags=re.IGNORECASE)
    items: list[ExtractedExpenseItem] = []
    pattern = re.compile(
        r"^(?P<qty>\d+(?:[.,]\d+)?)\s*"
        r"(?P<unit>kg|k|gr|g|lt|l|ml|atados?|unidades?|u)?\s*"
        r"(?:de\s+)?(?P<name>.+?)\s+a\s+\$?\s*"
        r"(?P<amount>\d[\d.,]*)$",
        flags=re.IGNORECASE,
    )
    unit_map = {
        "kg": "KG", "k": "KG", "gr": "GR", "g": "GR",
        "lt": "L", "l": "L", "ml": "ML", "atado": "ATADO",
        "atados": "ATADO", "unidad": "UNIDAD", "unidades": "UNIDAD", "u": "UNIDAD",
    }
    for segment in segments:
        match = pattern.match(segment.strip(" ."))
        if not match:
            continue
        quantity = Decimal(match.group("qty").replace(",", "."))
        raw_unit = (match.group("unit") or "UNIDAD").casefold()
        name = _clean(match.group("name")).strip("-:,. ").title()
        items.append(
            ExtractedExpenseItem(
                motivo=name,
                cantidad=quantity,
                unidad=unit_map.get(raw_unit, "UNIDAD"),
                subtotal=_money(match.group("amount")),
                confianza=Decimal("0.85"),
            )
        )
    return items


def _line_value(text: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}\s*[:\-]?\s*([^\n]+)", text, re.IGNORECASE)
    return _clean(match.group(1)) if match else None


def _extract_transfer_draft(text: str) -> ExpenseDocumentDraft:
    draft = ExpenseDocumentDraft(texto_extraido=text, medio_pago="TRANSFERENCIA")
    date_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", text)
    if date_match:
        draft.fecha = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
    amount_match = re.search(r"(?:comprobante de transferencia[\s\S]{0,80})\$\s*([\d.,]+)", text, re.I)
    if amount_match:
        draft.monto_total = _money(amount_match.group(1))
    draft.destinatario_pago = _line_value(text, "Destinatario")
    draft.identificador_pago = _line_value(text, "Id. Op.") or _line_value(text, "Id Op")

    comment_match = re.search(
        r"(\d+(?:[.,]\d+)?\s*(?:kg|k|gr|g|lt|l|ml|atados?|unidades?|u)?\s*"
        r"(?:de\s+)?.+?\s+a\s+\$?\s*\d[\d.,]*"
        r"(?:\s+y\s+.+?\s+a\s+\$?\s*\d[\d.,]*)+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if comment_match:
        draft.comentario = _clean(comment_match.group(1))
        draft.items = parse_purchase_comment(draft.comentario)
    return draft


def _field_value(fields: dict[str, Any], key: str) -> Any:
    field = fields.get(key) or {}
    for value_key in (
        "valueString", "valueDate", "valueNumber", "valueCurrency", "valueObject", "valueArray"
    ):
        if value_key in field:
            value = field[value_key]
            if value_key == "valueCurrency" and isinstance(value, dict):
                return value.get("amount")
            return value
    return field.get("content")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return None


def draft_from_azure_result(payload: dict[str, Any]) -> ExpenseDocumentDraft:
    result = payload.get("analyzeResult") or {}
    text = str(result.get("content") or "")
    documents = result.get("documents") or []
    fields = documents[0].get("fields", {}) if documents else {}
    transfer = "comprobante de transferencia" in text.casefold()
    draft = _extract_transfer_draft(text) if transfer else ExpenseDocumentDraft(texto_extraido=text)
    draft.motor_lectura = "azure-document-intelligence"

    vendor = _field_value(fields, "VendorName") or _field_value(fields, "MerchantName")
    if vendor and not transfer:
        draft.lugar = _clean(str(vendor))
    raw_date = _field_value(fields, "InvoiceDate") or _field_value(fields, "TransactionDate")
    if raw_date and draft.fecha is None:
        try:
            draft.fecha = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            pass
    total = _decimal_or_none(
        _field_value(fields, "InvoiceTotal") or _field_value(fields, "Total")
    )
    if total is not None:
        draft.monto_total = total

    if not draft.items:
        raw_items = _field_value(fields, "Items") or []
        for raw_item in raw_items:
            item_fields = raw_item.get("valueObject", raw_item) if isinstance(raw_item, dict) else {}
            name = _field_value(item_fields, "Description") or _field_value(item_fields, "Name")
            quantity = _decimal_or_none(_field_value(item_fields, "Quantity")) or Decimal("1")
            amount = _decimal_or_none(
                _field_value(item_fields, "Amount") or _field_value(item_fields, "TotalPrice")
            )
            if name and amount is not None:
                draft.items.append(
                    ExtractedExpenseItem(
                        motivo=_clean(str(name)),
                        cantidad=quantity,
                        unidad=_clean(str(_field_value(item_fields, "Unit") or "UNIDAD")).upper(),
                        subtotal=amount,
                        confianza=Decimal("0.80"),
                    )
                )

    document_confidence = documents[0].get("confidence") if documents else None
    draft.confianza = _decimal_or_none(document_confidence)
    item_total = sum((item.subtotal for item in draft.items), Decimal("0.00"))
    if draft.monto_total is not None and draft.items and item_total != draft.monto_total:
        draft.advertencias.append(
            f"Los ítems suman ${item_total:.2f} y el documento indica ${draft.monto_total:.2f}."
        )
    if not draft.items:
        draft.advertencias.append("No se pudieron separar los productos; completalos antes de confirmar.")
    return draft


class AzureDocumentReader:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def analyze(self, content: bytes, content_type: str) -> ExpenseDocumentDraft:
        endpoint = (self.settings.azure_document_intelligence_endpoint or "").rstrip("/")
        key = self.settings.azure_document_intelligence_key or ""
        if not endpoint or not key:
            raise RuntimeError(
                "Configura AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT y AZURE_DOCUMENT_INTELLIGENCE_KEY."
            )
        model = self.settings.azure_document_intelligence_model or "prebuilt-invoice"
        query = urlencode({"_overload": "analyzeDocument", "api-version": AZURE_API_VERSION})
        request = Request(
            f"{endpoint}/documentintelligence/documentModels/{model}:analyze?{query}",
            data=content,
            method="POST",
            headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": content_type},
        )
        try:
            with urlopen(request, timeout=45) as response:
                operation_url = response.headers.get("Operation-Location")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Azure rechazó el documento: {exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"No se pudo conectar con Azure: {exc.reason}") from exc
        if not operation_url:
            raise RuntimeError("Azure no devolvió la ubicación del resultado.")

        for _ in range(30):
            poll = Request(operation_url, headers={"Ocp-Apim-Subscription-Key": key})
            with urlopen(poll, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            status = payload.get("status")
            if status == "succeeded":
                return draft_from_azure_result(payload)
            if status == "failed":
                raise RuntimeError(f"Azure no pudo analizar el documento: {payload.get('error')}")
            time.sleep(1)
        raise RuntimeError("Azure demoró demasiado en analizar el documento.")


def _document_images(content: bytes, content_type: str) -> list[Any]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Faltan OpenCV y NumPy para procesar el documento localmente.") from exc

    images: list[Any] = []
    if content_type == "application/pdf":
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("Falta PyMuPDF para convertir el PDF en imágenes.") from exc
        with fitz.open(stream=content, filetype="pdf") as document:
            for page in document:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                images.append(
                    cv2.imdecode(
                        np.frombuffer(pixmap.tobytes("png"), np.uint8), cv2.IMREAD_COLOR
                    )
                )
    else:
        images.append(cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR))
    if not images or all(image is None for image in images):
        raise RuntimeError("No se pudo convertir el documento en una imagen legible.")
    return images


def read_qr_locally(content: bytes, content_type: str) -> str | None:
    try:
        import cv2
        images = _document_images(content, content_type)
    except (ImportError, RuntimeError):
        return None

    detector = cv2.QRCodeDetector()
    for image in images:
        if image is None:
            continue
        value, _, _ = detector.detectAndDecode(image)
        if value:
            return value
    return None


def draft_from_ocr_text(text: str) -> ExpenseDocumentDraft:
    if "transferencia" in text.casefold():
        draft = _extract_transfer_draft(text)
    else:
        draft = ExpenseDocumentDraft(
            fecha=_ticket_date(text),
            lugar=_ticket_place(text),
            monto_total=_ticket_total(text),
            medio_pago="TRANSFERENCIA" if "MERCADO PAGO" in text.upper() else None,
            texto_extraido=text,
            items=_thermal_ticket_items(text),
        )

    if not draft.items:
        for line in text.splitlines():
            parsed = parse_purchase_comment(line)
            if parsed:
                draft.items.extend(parsed)
    item_total = sum((item.subtotal for item in draft.items), Decimal("0.00"))
    if draft.monto_total is None and draft.items:
        draft.monto_total = item_total
    elif draft.monto_total is not None and len(draft.items) == 1 and item_total != draft.monto_total:
        only_item = draft.items[0]
        draft.items[0] = replace(
            only_item,
            subtotal=draft.monto_total,
            descripcion=_clean(
                f"{only_item.descripcion or only_item.motivo} | Importe ajustado al total del comprobante"
            ),
        )
    elif draft.monto_total is not None and draft.items and item_total != draft.monto_total:
        draft.advertencias.append(
            f"Los ítems detectados suman ${item_total:.2f} y el comprobante indica "
            f"${draft.monto_total:.2f}. Revisá los importes."
        )
    if not draft.items:
        draft.advertencias.append(
            "Tesseract leyó el texto, pero no pudo separar los productos automáticamente. "
            "Agregalos manualmente antes de confirmar."
        )
    return draft


def _preprocess_ocr_variants(image: Any) -> list[tuple[Any, int]]:
    import cv2

    height, width = image.shape[:2]
    original_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    original_gray = cv2.normalize(original_gray, None, 0, 255, cv2.NORM_MINMAX)
    original_otsu = cv2.threshold(
        original_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]
    scale = min(2.5, max(1.0, 1800 / max(width, 1)))
    if scale > 1:
        image = cv2.resize(
            image,
            (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_CUBIC,
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    background = cv2.GaussianBlur(gray, (0, 0), sigmaX=31, sigmaY=31)
    normalized = cv2.divide(gray, background, scale=255)
    enhanced = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(normalized)
    sharpened = cv2.addWeighted(enhanced, 1.7, cv2.GaussianBlur(enhanced, (0, 0), 1.2), -0.7, 0)
    otsu = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(
        sharpened,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        41,
        13,
    )
    return [
        (original_otsu, 6),
        (sharpened, 6),
        (otsu, 6),
        (adaptive, 6),
        (sharpened, 4),
    ]


def _text_and_confidence_from_ocr_data(data: dict[str, list[Any]]) -> tuple[str, list[Decimal]]:
    lines: dict[tuple[int, int, int, int], list[str]] = defaultdict(list)
    confidences: list[Decimal] = []
    words = data.get("text", [])
    for index, word in enumerate(words):
        clean_word = _clean(str(word))
        if not clean_word:
            continue
        key = tuple(
            int(data.get(name, [0] * len(words))[index])
            for name in ("page_num", "block_num", "par_num", "line_num")
        )
        lines[key].append(clean_word)
        try:
            confidence = Decimal(str(data.get("conf", ["-1"] * len(words))[index]))
        except Exception:
            continue
        if confidence >= 0:
            confidences.append(confidence)
    text = "\n".join(" ".join(lines[key]) for key in sorted(lines))
    return text, confidences


def _ocr_candidate_score(text: str, confidences: list[Decimal]) -> Decimal:
    mean_confidence = (
        sum(confidences, Decimal("0")) / Decimal(len(confidences))
        if confidences else Decimal("0")
    )
    upper = text.upper()
    keywords = sum(
        keyword in upper
        for keyword in (
            "FECHA", "TOTAL", "DESCRIP", "COMPROBANTE", "CUIT",
            "CANTIDAD", "IMPORTE", "MERCADO PAGO",
        )
    )
    semantic_matches = (
        len(re.findall(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text))
        + (3 if re.search(r"\d+(?:[.,]\d+)?\s*[xX]\s*[$5S]?\s*\d", text) else 0)
        + (2 if re.search(r"(?:TOTAL|MERCADO\s+PAGO)[^\n]*\d", text, re.I) else 0)
    )
    structured = draft_from_ocr_text(text)
    structured_score = (
        (25 if structured.fecha else 0)
        + (25 if structured.monto_total is not None else 0)
        + (20 if structured.lugar else 0)
        + (35 if structured.items else 0)
    )
    return (
        mean_confidence
        + Decimal(keywords * 7)
        + Decimal(semantic_matches * 8)
        + Decimal(structured_score)
        + Decimal(min(len(text), 1500)) / Decimal("100")
    )


def _configure_local_tesseract(pytesseract: Any, language: str) -> str:
    """Locate the Windows executable and user-scoped language model when needed."""
    if shutil.which("tesseract") is None:
        windows_binary = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / (
            "Tesseract-OCR/tesseract.exe"
        )
        if windows_binary.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(windows_binary)

    local_roots = []
    if os.environ.get("LOCALAPPDATA"):
        local_roots.append(Path(os.environ["LOCALAPPDATA"]))
    if os.name == "nt":
        local_roots.append(Path.home() / "AppData" / "Local")
    for local_root in local_roots:
        tessdata_dir = local_root / "GastroFlow" / "tessdata"
        if (tessdata_dir / f"{language}.traineddata").is_file():
            # Tesseract on Windows resolves quoted config paths inconsistently
            # through pytesseract; its supported environment variable is stable.
            os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
            break
    return ""


class TesseractDocumentReader:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def analyze(self, content: bytes, content_type: str) -> ExpenseDocumentDraft:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:
            raise RuntimeError(
                "Faltan las dependencias locales de Tesseract. Instalá requirements-internal.txt."
            ) from exc

        language = self.settings.tesseract_language or "spa"
        tessdata_config = _configure_local_tesseract(pytesseract, language)
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise RuntimeError(
                "No se encontró el ejecutable Tesseract OCR. Instalá tesseract-ocr y el idioma español."
            ) from exc

        texts: list[str] = []
        confidences: list[Decimal] = []
        for image in _document_images(content, content_type):
            if image is None:
                continue
            candidates: list[tuple[Decimal, str, list[Decimal]]] = []
            for processed, page_segmentation_mode in _preprocess_ocr_variants(image):
                config = (
                    f"{tessdata_config} --oem 1 --psm {page_segmentation_mode} "
                    "-c preserve_interword_spaces=1"
                ).strip()
                data = pytesseract.image_to_data(
                    processed, lang=language, config=config, output_type=Output.DICT
                )
                candidate_text, candidate_confidences = _text_and_confidence_from_ocr_data(data)
                if candidate_text:
                    candidates.append((
                        _ocr_candidate_score(candidate_text, candidate_confidences),
                        candidate_text,
                        candidate_confidences,
                    ))
            if candidates:
                _, best_text, best_confidences = max(candidates, key=lambda candidate: candidate[0])
                texts.append(best_text)
                confidences.extend(best_confidences)

        text = "\n".join(texts).strip()
        if not text:
            raise RuntimeError("Tesseract no pudo reconocer texto en el documento.")
        draft = draft_from_ocr_text(text)
        draft.motor_lectura = "tesseract-local"
        if confidences:
            draft.confianza = (
                sum(confidences, Decimal("0")) / Decimal(len(confidences)) / Decimal("100")
            ).quantize(Decimal("0.0001"))
        return draft


class HybridExpenseDocumentReader:
    def __init__(
        self,
        primary: DocumentReader | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        if primary is not None:
            self.primary = primary
        elif self.settings.expense_ocr_engine.casefold() == "azure":
            self.primary = AzureDocumentReader(self.settings)
        elif self.settings.expense_ocr_engine.casefold() == "tesseract":
            self.primary = TesseractDocumentReader(self.settings)
        else:
            raise RuntimeError(
                f"Motor OCR desconocido: {self.settings.expense_ocr_engine!r}."
            )

    def analyze(self, content: bytes, content_type: str) -> ExpenseDocumentDraft:
        qr_value = read_qr_locally(content, content_type)
        draft = self.primary.analyze(content, content_type)
        draft.qr_contenido = qr_value
        if qr_value:
            draft.motor_lectura = f"qr-local+{draft.motor_lectura}"
        return draft
