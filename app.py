from flask import Flask, jsonify, Response
import requests
from requests.auth import HTTPBasicAuth
import os

app = Flask(__name__)

CH_API_KEY = os.environ.get("CH_API_KEY")
BASE_URL = "https://api.company-information.service.gov.uk"

def ch_get_json(url_or_path):
    url = url_or_path if url_or_path.startswith("http") else BASE_URL + url_or_path
    r = requests.get(url, auth=HTTPBasicAuth(CH_API_KEY, ""))
    r.raise_for_status()
    return r.json()

def ch_get_raw(url, accept=None, allow_redirects=True):
    headers = {}
    if accept:
        headers["Accept"] = accept
    r = requests.get(
        url,
        auth=HTTPBasicAuth(CH_API_KEY, ""),
        headers=headers,
        allow_redirects=allow_redirects,
        stream=True
    )
    r.raise_for_status()
    return r

def get_latest_accounts_filing(company_number):
    filing = ch_get_json(f"/company/{company_number}/filing-history")
    for item in filing.get("items", []):
        if item.get("type") == "AA":
            return item
    return None

def get_latest_accounts_metadata(company_number):
    latest = get_latest_accounts_filing(company_number)
    if not latest:
        return None

    meta_url = latest.get("links", {}).get("document_metadata")
    if not meta_url:
        return None

    meta = ch_get_json(meta_url)
    return {
        "filing": latest,
        "metadata": meta,
        "document_metadata_url": meta_url,
        "document_content_url": meta_url + "/content"
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
        company_profile = ch_get_json(f"/company/{company_number}")
        officers = ch_get_json(f"/company/{company_number}/officers")
        pscs = ch_get_json(f"/company/{company_number}/persons-with-significant-control")
        charges = ch_get_json(f"/company/{company_number}/charges")
        filing_history = ch_get_json(f"/company/{company_number}/filing-history")
        latest_accounts = get_latest_accounts_metadata(company_number)

        return jsonify({
            "company_profile": company_profile,
            "officers": officers,
            "pscs": pscs,
            "charges": charges,
            "filing_history": filing_history,
            "latest_accounts": latest_accounts
        })
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/rix-credit/company/<company_number>/latest-accounts-metadata")
def latest_accounts_metadata(company_number):
    try:
        data = get_latest_accounts_metadata(company_number)
        if not data:
            return {"error": "No accounts filing found"}, 404
        return jsonify(data)
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/rix-credit/company/<company_number>/latest-accounts.pdf")
def latest_accounts_pdf(company_number):
    try:
        data = get_latest_accounts_metadata(company_number)
        if not data:
            return {"error": "No accounts filing found"}, 404

        meta = data["metadata"]
        resources = meta.get("resources", {})

        if "application/pdf" not in resources:
            return {"error": "PDF not available for this filing"}, 404

        content_url = data["document_content_url"]

        # Request the document content as PDF.
        # Companies House returns a redirect to the file location.
        r = ch_get_raw(content_url, accept="application/pdf", allow_redirects=True)

        return Response(
            r.content,
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{company_number}-latest-accounts.pdf"'
            }
        )
    except Exception as e:
        return {"error": str(e)}, 500
