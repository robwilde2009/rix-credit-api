from flask import Flask, jsonify
import requests
from requests.auth import HTTPBasicAuth
import os
import re

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
        timeout=60,
        allow_redirects=True
    )
    r.raise_for_status()
    return r.text


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
            text_content = None
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


def extract_accounts_financials_from_text(text):
    if not text:
        return {}

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def find_value(patterns):
        for pattern in patterns:
            for line in lines:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    return parse_number(match.group(1))
        return None

    return {
        "tangible_assets": find_value([
            r"Fixed assets\s+([\d,.\-\(\)]+)",
            r"Tangible assets\s+([\d,.\-\(\)]+)",
            r"Property.*equipment\s+([\d,.\-\(\)]+)",
            r"Property, plant and equipment\s+([\d,.\-\(\)]+)",
            r"Total fixed assets\s+([\d,.\-\(\)]+)"
        ]),

        "debtors": find_value([
            r"Debtors\s+([\d,.\-\(\)]+)",
            r"Trade debtors\s+([\d,.\-\(\)]+)"
        ]),

        "cash": find_value([
            r"Cash at bank\s+([\d,.\-\(\)]+)",
            r"Cash at bank and in hand\s+([\d,.\-\(\)]+)",
            r"Cash\s+([\d,.\-\(\)]+)"
        ]),

        "total_current_assets": find_value([
            r"Current assets\s+([\d,.\-\(\)]+)",
            r"Total current assets\s+([\d,.\-\(\)]+)"
        ]),

        "total_current_liabilities": find_value([
            r"Creditors[: ]+amounts falling due within one year\s+([\d,.\-\(\)]+)",
            r"Creditors.*within one year\s+([\d,.\-\(\)]+)",
            r"Current liabilities\s+([\d,.\-\(\)]+)",
            r"Total current liabilities\s+([\d,.\-\(\)]+)"
        ]),

        "working_capital": find_value([
            r"Working capital\s+([\d,.\-\(\)]+)"
        ]),

        "total_net_assets": find_value([
            r"Net assets\s+([\d,.\-\(\)]+)",
            r"Total net assets\s+([\d,.\-\(\)]+)"
        ]),

        "shareholders_funds": find_value([
            r"Total shareholders'? funds\s+([\d,.\-\(\)]+)",
            r"Shareholders'? funds\s+([\d,.\-\(\)]+)",
            r"Equity\s+([\d,.\-\(\)]+)"
        ]),

        "total_long_term_liabilities": find_value([
            r"Creditors[: ]+amounts falling due after more than one year\s+([\d,.\-\(\)]+)",
            r"Creditors.*after more than one year\s+([\d,.\-\(\)]+)",
            r"Long term liabilities\s+([\d,.\-\(\)]+)",
            r"Total long term liabilities\s+([\d,.\-\(\)]+)"
        ]),

        "current_ratio": find_value([
            r"Current ratio\s+([\d,.\-\(\)]+)"
        ]),

        "acid_test": find_value([
            r"Acid test\s+([\d,.\-\(\)]+)"
        ]),

        "borrowing_ratio": find_value([
            r"Borrowing ratio %\s+([\d,.\-\(\)]+)"
        ]),

        "equity_gearing": find_value([
            r"Equity gearing %\s+([\d,.\-\(\)]+)"
        ]),

        "debt_gearing": find_value([
            r"Debt gearing %\s+([\d,.\-\(\)]+)"
        ]),

        "depreciation": find_value([
            r"Depreciation charges\s+([\d,.\-\(\)]+)"
        ]),

        "employees": find_value([
            r"Number of employees\s+([\d,.\-\(\)]+)",
            r"employees\s+([\d,.\-\(\)]+)"
        ])
    }


def get_recent_accounts_financials(company_number, limit=3):
    accounts = get_recent_accounts_text(company_number, limit=limit)
    results = []

    for account in accounts:
        text = account.get("text")
        extracted = extract_accounts_financials_from_text(text) if text else {}

        results.append({
            "made_up_to": account.get("made_up_to"),
            "filing_date": account.get("filing_date"),
            "content_type_used": account.get("content_type_used"),
            "document_metadata_url": account.get("document_metadata_url"),
            "document_content_url": account.get("document_content_url"),
            **extracted
        })

    return results


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


@app.route("/rix-credit/company/<company_number>/recent-accounts-financials")
def recent_accounts_financials(company_number):
    try:
        data = get_recent_accounts_financials(company_number, limit=3)
        return jsonify({"recent_accounts_financials": data})
    except Exception as e:
        return {"error": str(e)}, 500
