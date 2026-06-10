import logging
import re
import time
from pathlib import Path

from decouple import config

logger = logging.getLogger(__name__)


class SerialImportParseError(Exception):
    """Raised when an uploaded serial-number document cannot be parsed."""


SERIAL_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "serials": {
            "type": "array",
            "description": (
                "List of unique serial numbers visible on the document. "
                "A serial number is an alphanumeric identifier that uniquely "
                "identifies one physical unit — typically 5 to 30 characters, "
                "mixing letters and digits (e.g. 'C02NQCC6FY17', '4CE0460D0G', "
                "'SN-2026-0001'). It commonly appears next to a label like "
                "'Serial No.', 'S/N', '(S) Serial', or 'Asset Tag', or printed "
                "alone underneath a barcode. "
                "Include each distinct serial only once even if printed many "
                "times. Preserve exact characters with original casing. "
                "Return an empty list ONLY if the document genuinely contains "
                "no serial-like identifier."
            ),
            "items": {
                "type": "string",
                "description": "A single serial number, exactly as printed.",
            },
        }
    },
    "required": ["serials"],
}

SERIAL_EXTRACTION_SYSTEM_PROMPT = (
    "You are extracting serial numbers from photos or scans of hardware "
    "stickers, asset tags, packing slips, and inspection certificates. "
    "Treat any short alphanumeric code (letters + digits, no spaces, length "
    "5-30) printed under or next to a barcode as a serial unless it is "
    "clearly labeled as something else (Part No., Model No., Product No., "
    "Lot, Batch, Rev, Version). When the same value appears multiple times, "
    "list it only once. Never invent characters; if you cannot read a "
    "character clearly, prefer to omit the value rather than guess."
)


def extract_serials_with_llamaextract(uploaded_file, suffix):
    """
    Uploads the file to LlamaCloud and runs a stateless v2 extraction.
    """
    import requests

    api_key = config("LLAMA_CLOUD_API_KEY", default="").strip()
    if not api_key:
        raise SerialImportParseError(
            "LLAMA_CLOUD_API_KEY is not configured on the backend."
        )
    project_id = config("LLAMA_CLOUD_PROJECT_ID", default="").strip()
    if not project_id:
        raise SerialImportParseError(
            "LLAMA_CLOUD_PROJECT_ID is not configured on the backend."
        )

    tier_raw = config("LLAMA_EXTRACT_TIER", default="agentic")
    tier = tier_raw.strip().lower() or "agentic"
    if tier not in {"agentic", "cost_effective"}:
        raise SerialImportParseError(
            f"LLAMA_EXTRACT_TIER must be 'agentic' or 'cost_effective'; got {tier}"
        )
    base_url = config("LLAMA_CLOUD_BASE_URL", default="https://api.cloud.llamaindex.ai").rstrip("/")
    poll_timeout = int(config("LLAMA_EXTRACT_TIMEOUT_SECONDS", default="90"))
    headers = {"Authorization": f"Bearer {api_key}"}
    qs = {"project_id": project_id}

    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    filename = uploaded_file.name or f"upload{suffix}"

    try:
        upload_resp = requests.post(
            f"{base_url}/api/v1/beta/files",
            headers=headers,
            files={"file": (filename, file_bytes)},
            data={"purpose": "extract"},
            params=qs,
            timeout=30,
        )
        upload_resp.raise_for_status()
        file_id = upload_resp.json().get("id")
        if not file_id:
            raise SerialImportParseError("LlamaCloud file upload returned no id.")

        create_resp = requests.post(
            f"{base_url}/api/v2/extract",
            headers={**headers, "Content-Type": "application/json"},
            params=qs,
            json={
                "file_input": file_id,
                "configuration": {
                    "tier": tier,
                    "extraction_target": "per_doc",
                    "data_schema": SERIAL_EXTRACTION_SCHEMA,
                    "system_prompt": SERIAL_EXTRACTION_SYSTEM_PROMPT,
                    "cite_sources": True,
                    "confidence_scores": False,
                },
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        job_id = create_resp.json().get("id")
        if not job_id:
            raise SerialImportParseError("LlamaExtract job creation returned no id.")

        deadline = time.monotonic() + poll_timeout
        result_data = None
        while time.monotonic() < deadline:
            status_resp = requests.get(
                f"{base_url}/api/v2/extract/{job_id}",
                headers=headers,
                params={**qs, "expand": ["extract_metadata", "metadata"]},
                timeout=15,
            )
            status_resp.raise_for_status()
            body = status_resp.json()
            state = (body.get("status") or "").upper()
            if state in {"SUCCESS", "COMPLETED"}:
                result_data = body.get("extract_result") or body.get("data") or {}
                break
            if state in {"ERROR", "FAILED", "CANCELLED"}:
                raise SerialImportParseError(
                    f"LlamaExtract job failed: {body.get('error') or state}"
                )
            time.sleep(2)

        if result_data is None:
            raise SerialImportParseError("LlamaExtract timed out before completion.")
    except requests.RequestException as exc:
        raise SerialImportParseError(f"LlamaCloud request failed: {exc}") from exc

    serials = result_data.get("serials") or [] if isinstance(result_data, dict) else []
    candidates = []
    seen = set()
    for index, serial in enumerate(serials, start=1):
        if not isinstance(serial, str):
            continue
        cleaned = serial.strip()
        if not cleaned or len(cleaned) > 100:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "row_number": index,
            "serial_number": cleaned,
            "raw_text": cleaned,
        })
    return candidates


TEXT_EXTENSIONS = {".txt", ".csv", ".tsv"}
DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".docx"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

SERIAL_LINE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:[-*•]\s*)|(?:\d+[\).\-\s:]+)|(?:serial\s*(?:no\.?|number)?|s/n|sn|asset\s*tag)\s*[:#\-]?\s*)+",
    re.IGNORECASE,
)


def _clean_serial_line(line):
    return SERIAL_LINE_PREFIX_RE.sub("", str(line or "").strip()).strip()


def parse_serial_candidates(text):
    """
    Trivial line splitter for pasted text or text-file uploads. Each non-empty
    line becomes one candidate. The caller is responsible for clean input.
    """
    candidates = []
    seen = set()
    row_number = 0
    for line in str(text or "").splitlines():
        raw_text = line.strip()
        cleaned = _clean_serial_line(raw_text)
        row_number += 1
        if not cleaned or len(cleaned) > 100:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "row_number": row_number,
            "serial_number": cleaned,
            "raw_text": raw_text,
        })
    return candidates


def _decode_text_upload(uploaded_file):
    data = uploaded_file.read()
    uploaded_file.seek(0)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SerialImportParseError("Could not decode the uploaded text file.")


def extract_candidates_from_upload(uploaded_file):
    """
    Returns (candidates, mode).
    - text/csv/tsv → line-split (mode='line_split')
    - pdf/image/docx → LlamaExtract schema-driven extraction (mode='llamaextract')
    """
    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        raise SerialImportParseError("Uploaded file exceeds the 20 MB size limit.")

    suffix = Path(uploaded_file.name or "").suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        text = _decode_text_upload(uploaded_file)
        return parse_serial_candidates(text), "line_split"
    if suffix in DOCUMENT_EXTENSIONS:
        candidates = extract_serials_with_llamaextract(uploaded_file, suffix)
        return candidates, "llamaextract"

    allowed = ", ".join(sorted(TEXT_EXTENSIONS | DOCUMENT_EXTENSIONS))
    raise SerialImportParseError(f"Unsupported file type '{suffix}'. Allowed: {allowed}.")
