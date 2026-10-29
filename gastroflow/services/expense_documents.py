from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
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
    clean = value.replace("$", "").replace(" ", "")
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif clean.count(".") == 1 and len(clean.rsplit(".", 1)[1]) == 3:
        clean = clean.replace(".", "")
    return Decimal(clean).quantize(Decimal("0.01"))


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
        draft = ExpenseDocumentDraft(texto_extraido=text)
        date_match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text)
        if date_match:
            raw_date = date_match.group(1).replace("-", "/")
            if len(raw_date.rsplit("/", 1)[1]) == 2:
                raw_date = raw_date.rsplit("/", 1)[0] + "/20" + raw_date.rsplit("/", 1)[1]
            try:
                draft.fecha = datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                pass
        total_matches = re.findall(
            r"(?:TOTAL|IMPORTE)\s*[:$]?\s*\$?\s*([\d.,]+)", text, re.IGNORECASE
        )
        if total_matches:
            draft.monto_total = _money(total_matches[-1])

    if not draft.items:
        for line in text.splitlines():
            parsed = parse_purchase_comment(line)
            if parsed:
                draft.items.extend(parsed)
    if not draft.items:
        draft.advertencias.append(
            "Tesseract leyó el texto, pero no pudo separar los productos automáticamente. "
            "Agregalos manualmente antes de confirmar."
        )
    return draft


class TesseractDocumentReader:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def analyze(self, content: bytes, content_type: str) -> ExpenseDocumentDraft:
        try:
            import cv2
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:
            raise RuntimeError(
                "Faltan las dependencias locales de Tesseract. Instalá requirements-internal.txt."
            ) from exc

        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise RuntimeError(
                "No se encontró el ejecutable Tesseract OCR. Instalá tesseract-ocr y el idioma español."
            ) from exc

        texts: list[str] = []
        confidences: list[Decimal] = []
        language = self.settings.tesseract_language or "spa"
        for image in _document_images(content, content_type):
            if image is None:
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
            processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            config = "--oem 1 --psm 6"
            texts.append(pytesseract.image_to_string(processed, lang=language, config=config))
            data = pytesseract.image_to_data(
                processed, lang=language, config=config, output_type=Output.DICT
            )
            for raw_confidence in data.get("conf", []):
                try:
                    confidence = Decimal(str(raw_confidence))
                except Exception:
                    continue
                if confidence >= 0:
                    confidences.append(confidence)

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
