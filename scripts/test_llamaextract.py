"""
Standalone smoke test for LlamaExtract v2 serial-number extraction.

Usage (from ams-backend with the venv activated):
    python scripts/test_llamaextract.py "C:\\path\\to\\image.jpg"
    python scripts/test_llamaextract.py "C:\\path\\to\\doc.pdf" --tier agentic

Uses the v2 stateless extract endpoint — no agent pre-registration needed.
Reads LLAMA_CLOUD_API_KEY and LLAMA_CLOUD_PROJECT_ID from .env.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ams.settings")
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from decouple import Config, RepositoryEnv
import requests

ENV_FILE = PROJECT_DIR / ".env"
if not ENV_FILE.exists():
    sys.exit(f".env not found at {ENV_FILE}")
env = Config(RepositoryEnv(str(ENV_FILE)))

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_path", help="Absolute path to the image/PDF/docx to extract from.")
    parser.add_argument("--tier", default=None, help="agentic | cost_effective")
    parser.add_argument("--timeout", type=int, default=90, help="Polling timeout in seconds.")
    args = parser.parse_args()

    file_path = Path(args.file_path)
    if not file_path.exists():
        sys.exit(f"File not found: {file_path}")

    api_key = env("LLAMA_CLOUD_API_KEY", default="").strip()
    if not api_key:
        sys.exit("LLAMA_CLOUD_API_KEY missing in .env")
    project_id = env("LLAMA_CLOUD_PROJECT_ID", default="").strip()
    if not project_id:
        sys.exit("LLAMA_CLOUD_PROJECT_ID missing in .env")

    tier = (args.tier or env("LLAMA_EXTRACT_TIER", default="agentic")).lower()
    if tier not in {"agentic", "cost_effective"}:
        sys.exit(f"--tier must be 'agentic' or 'cost_effective'; got {tier}")
    base_url = env("LLAMA_CLOUD_BASE_URL", default="https://api.cloud.llamaindex.ai").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    qs = {"project_id": project_id}

    print(f"→ Uploading {file_path.name} ({file_path.stat().st_size} bytes)")
    with file_path.open("rb") as handle:
        upload_resp = requests.post(
            f"{base_url}/api/v1/beta/files",
            headers=headers,
            files={"file": (file_path.name, handle)},
            data={"purpose": "extract"},
            params=qs,
            timeout=30,
        )
    print(f"  upload status {upload_resp.status_code}")
    if upload_resp.status_code >= 400:
        print(upload_resp.text)
        sys.exit(1)
    file_id = upload_resp.json().get("id")
    print(f"  file_id: {file_id}")

    print(f"→ Creating extraction job (tier={tier}) via v2 stateless endpoint")
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
    print(f"  job create status {create_resp.status_code}")
    if create_resp.status_code >= 400:
        print(create_resp.text)
        sys.exit(1)
    job_id = create_resp.json().get("id")
    print(f"  job_id: {job_id}")

    print("→ Polling job status...")
    deadline = time.monotonic() + args.timeout
    final_body = None
    while time.monotonic() < deadline:
        status_resp = requests.get(
            f"{base_url}/api/v2/extract/{job_id}",
            headers=headers,
            params={**qs, "expand": ["extract_metadata", "metadata"]},
            timeout=15,
        )
        body = status_resp.json()
        state = (body.get("status") or "").upper()
        print(f"  [{int(time.monotonic())}] status={state}")
        if state in {"SUCCESS", "COMPLETED"}:
            final_body = body
            break
        if state in {"ERROR", "FAILED", "CANCELLED"}:
            print(json.dumps(body, indent=2))
            sys.exit(1)
        time.sleep(2)

    if final_body is None:
        sys.exit("Timed out waiting for job.")

    print("\n=== RESULT ===")
    print(json.dumps(final_body, indent=2))

    parse_job_id = (final_body.get("extract_metadata") or {}).get("parse_job_id")
    if parse_job_id:
        print(f"\n=== PARSED TEXT (job {parse_job_id}) ===")
        parse_resp = requests.get(
            f"{base_url}/api/v2/parse/{parse_job_id}",
            headers=headers,
            params={**qs, "expand": "markdown,text"},
            timeout=15,
        )
        if parse_resp.status_code == 200:
            body = parse_resp.json()
            print("--- markdown ---")
            print(body.get("markdown") or "(empty)")
            print("\n--- text ---")
            print(body.get("text") or "(empty)")
        else:
            print(f"  parse fetch returned {parse_resp.status_code}: {parse_resp.text[:500]}")

    data = (final_body.get("extract_result") or final_body.get("data") or {})
    if isinstance(data, dict):
        serials = data.get("serials") or []
    else:
        serials = []
    print("\n=== SERIALS EXTRACTED ===")
    if serials:
        for s in serials:
            print(f"  - {s}")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
