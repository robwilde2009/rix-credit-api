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
    r = requests.get(url, auth=HTTPBasicAuth(CH_API_KEY, ""), timeout=30)
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

        # Prefer XHTML because it is text and easier for GPT to use
        if "application/xhtml+xml" in resources:
            raw = ch_get_text(content_url, accept="application/xhtml+xml")
            text_content = clean_xhtml_to_text(raw)
            content_type_used = "application/xhtml+xml"

        # Fallback to iXBRL / XML-like content if present
        elif "application/xml" in resources:
            raw = ch_get_text(content_url, accept="application/xml")
            text_content = clean_xhtml_to_text(raw)
            content_type_used = "application/xml"

        # If only PDF is available, keep the link but do not try to OCR here
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
