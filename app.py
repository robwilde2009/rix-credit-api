from flask import Flask, jsonify
import requests
from requests.auth import HTTPBasicAuth
import os

app = Flask(__name__)

CH_API_KEY = os.environ.get("CH_API_KEY")
BASE_URL = "https://api.company-information.service.gov.uk"

def ch_get_json(url_or_path):
    url = url_or_path if url_or_path.startswith("http") else BASE_URL + url_or_path
    r = requests.get(url, auth=HTTPBasicAuth(CH_API_KEY, ""), timeout=30)
    r.raise_for_status()
    return r.json()

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
