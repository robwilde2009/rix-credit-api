from flask import Flask, jsonify
import requests
from requests.auth import HTTPBasicAuth
import os
import re

app = Flask(__name__)

CH_API_KEY = os.environ.get("CH_API_KEY")
BASE_URL = "https://api.company-information.service.gov.uk"


def ch_get_json(path):
    url = BASE_URL + path
    r = requests.get(url, auth=HTTPBasicAuth(CH_API_KEY, ""), timeout=20)
    r.raise_for_status()
    return r.json()


def parse_number(value):
    if not value:
        return None
    value = str(value).replace(",", "").replace("£", "").strip()
    try:
        return float(value)
    except:
        return None


def get_recent_accounts(company_number):
    filing = ch_get_json(f"/company/{company_number}/filing-history")

    accounts = []
    for item in filing.get("items", []):
        if item.get("type") == "AA":
            accounts.append({
                "date": item.get("date"),
                "made_up_to": item.get("description_values", {}).get("made_up_date"),
                "document_metadata": item.get("links", {}).get("document_metadata")
            })
        if len(accounts) == 3:
            break

    return accounts


@app.route("/")
def home():
    return {"status": "ok"}


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
            "recent_accounts": get_recent_accounts(company_number)
        })
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/rix-credit/company/<company_number>/latest-accounts-financials")
def latest_accounts_financials(company_number):
    try:
        accounts = get_recent_accounts(company_number)
        if not accounts:
            return jsonify({"latest_accounts_financials": None})

        latest = accounts[0]

        return jsonify({
            "latest_accounts_financials": {
                "made_up_to": latest["made_up_to"],
                "filing_date": latest["date"],
                "note": "Financial extraction disabled for stability - use PDF manually if needed"
            }
        })

    except Exception as e:
        return {"error": str(e)}, 500
