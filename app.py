from flask import Flask, jsonify
import requests
from requests.auth import HTTPBasicAuth
import os
import re
import io
import pdfplumber

app = Flask(__name__)

CH_API_KEY = os.environ.get("CH_API_KEY")
BASE_URL = "https://api.company-information.service.gov.uk"


def ch_get_json(url_or_path):
    url = url_or_path if url_or_path.startswith("http") else BASE_URL + url_or_path
    r = requests.get(
        url,
        auth=HTTPBasicAuth(CH_API_KEY, ""),
        timeout=30
    )
    r.raise_for_status()
    return r.json()


def ch_get_text(url, accept=None):
    headers = {}
    if accept:
        headers["Accept"] = accept

    r = requests.get(
        url,
        auth=HTTPBasicAuth(CH_API_KEY, ""),
        headers=headers,
        timeout=45,
        allow_redirects=True
    )
    r.raise_for_status()
    return r.text


def ch_get_bytes(url, accept=None):
    headers = {}
    if accept:
        headers["Accept"] = accept

    r = requests.get(
        url,
        auth=HTTPBasicAuth(CH_API_KEY, ""),
        headers=headers,
        timeout=60,
        allow_redirects=True
    )
    r.raise_for_status()
    return r.content


def clean_xhtml_to_text(xhtml):
    text = re.sub(r"<script.*?</script>", " ", xhtml, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</tr>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</td>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\r", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_text_from_pdf_bytes(pdf_bytes, max_pages=15):
    texts = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text()
            if page_text:
                texts.append(page_text)

    return "\n\n".join(texts).strip()


def parse_number(value):
    if value is None:
        return None

    value = str(value).strip()
    if value in ["", "-", "—"]:
        return None

    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative = True
        value = value[1:-1]

    value = value.replace(",", "").replace("£", "").strip()

    try:
        if "." in value:
            num = float(value)
        else:
            num = int(value)
        return -num if negative else num
    except Exception:
        return None


def get_recent_accounts_filings(company_number, limit=3):
    filing = ch_get_json(f"/company/{company_number}/filing-history")
    results = []

    for item in filing.get("items", []):
        if item.get("type") == "AA":
            results.append(item)
        if len(results) >= limit:
            break

    return results


def get_recent_accounts_metadata(company_number, limit=3):
    filings = get_recent_accounts_filings(company_number, limit=limit)
    results = []

    for filing in filings:
        meta_url = filing.get("links", {}).get("document_metadata")
        if not meta_url:
            continue

        meta = ch_get_json(meta_url)
        results.append({
            "filing_date": filing.get("date"),
            "made_up_to": filing.get("description_values", {}).get("made_up_date"),
            "document_metadata_url": meta_url,
            "document_content_url": meta_url + "/content",
            "metadata": meta
        })

    return results


def get_recent_accounts_text(company_number, limit=3):
    accounts = get_recent_accounts_metadata(company_number, limit=limit)
    results = []

    for account in accounts:
        metadata = account.get("metadata", {})
        resources = metadata.get("resources", {})
        content_url = account.get("document_content_url")

        text_content = None
        content_type_used = None

        if "application/xhtml+xml" in resources:
            raw = ch_get_text(content_url, accept="application/xhtml+xml")
            text_content = clean_xhtml_to_text(raw)
            content_type_used = "application/xhtml+xml"

        elif "application/xml" in resources:
            raw = ch_get_text(content_url, accept="application/xml")
            text_content = clean_xhtml_to_text(raw)
            content_type_used = "application/xml"

        elif "application/pdf" in resources:
            pdf_bytes = ch_get_bytes(content_url, accept="application/pdf")
            text_content = extract_text_from_pdf_bytes(pdf_bytes, max_pages=15)
            content_type_used = "application/pdf"

        results.append({
            "made_up_to": account.get("made_up_to"),
            "filing_date": account.get("filing_date"),
            "document_metadata_url": account.get("document_metadata_url"),
            "document_content_url": content_url,
            "content_type_used": content_type_used,
            "text": text_content
        })

    return results


def extract_latest_accounts_financials(text):
    if not text:
        return {}

    text = text[:50000]
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def find_value(label_patterns):
        for i, line in enumerate(lines):
            for pattern in label_patterns:
                if re.search(pattern, line, flags=re.IGNORECASE):
                    same_line_match = re.search(r"([\d,.\-\(\)]+)$", line)
                    if same_line_match:
                        return parse_number(same_line_match.group(1))

                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        next_match = re.search(r"([\d,.\-\(\)]+)", next_line)
                        if next_match:
                            return parse_number(next_match.group(1))
        return None

    return {
        "fixed_assets": find_value([
            r"fixed assets",
            r"tangible assets",
            r"total fixed assets"
        ]),
        "debtors": find_value([
            r"debtors",
            r"trade debtors"
        ]),
        "cash": find_value([
            r"cash at bank and in hand",
            r"cash at bank",
            r"cash and cash equivalents",
            r"cash"
        ]),
        "current_assets": find_value([
            r"current assets",
            r"total current assets"
        ]),
        "current_liabilities": find_value([
            r"creditors.*within one year",
            r"current liabilities",
            r"total current liabilities"
        ]),
        "working_capital": find_value([
            r"working capital"
        ]),
        "net_assets": find_value([
            r"net assets",
            r"total net assets"
        ]),
        "shareholders_funds": find_value([
            r"shareholders'? funds",
            r"total shareholders'? funds",
            r"equity"
        ]),
        "employees": find_value([
            r"number of employees"
        ])
    }


def get_latest_accounts_financials(company_number):
    accounts = get_recent_accounts_text(company_number, limit=1)
    if not accounts:
        return None

    account = accounts[0]
    text = account.get("text")
    extracted = extract_latest_accounts_financials(text) if text else {}

    return {
        "made_up_to": account.get("made_up_to"),
        "filing_date": account.get("filing_date"),
        "content_type_used": account.get("content_type_used"),
        "document_metadata_url": account.get("document_metadata_url"),
        "document_content_url": account.get("document_content_url"),
        "text_found": bool(text),
        **extracted
    }


@app.route("/")
def home():
    return {"status": "ok", "message": "Rix Credit API is live"}


@app.route("/health")
def health():
    return {"status": "healthy"}


@app.route("/rix-credit/company/<company_number>")
def get_company(company_number):
    try:
        return jsonify({
            "company_profile": ch_get_json(f"/company/{company_number}"),
            "officers": ch_get_json(f"/company/{company_number}/officers"),
            "pscs": ch_get_json(f"/company/{company_number}/persons-with-significant-control"),
            "charges": ch_get_json(f"/company/{company_number}/charges"),
            "filing_history": ch_get_json(f"/company/{company_number}/filing-history"),
            "recent_accounts": get_recent_accounts_metadata(company_number, limit=3)
        })
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/rix-credit/company/<company_number>/recent-accounts-metadata")
def recent_accounts_metadata(company_number):
    try:
        data = get_recent_accounts_metadata(company_number, limit=3)
        return jsonify({"recent_accounts": data})
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/rix-credit/company/<company_number>/recent-accounts-text")
def recent_accounts_text(company_number):
    try:
        data = get_recent_accounts_text(company_number, limit=3)
        return jsonify({"accounts_text": data})
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/rix-credit/company/<company_number>/latest-accounts-financials")
def latest_accounts_financials(company_number):
    try:
        data = get_latest_accounts_financials(company_number)
        return jsonify({"latest_accounts_financials": data})
    except Exception as e:
        return {"error": str(e)}, 500
