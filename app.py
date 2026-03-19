from flask import Flask, jsonify
import requests
from requests.auth import HTTPBasicAuth
import os

app = Flask(__name__)

CH_API_KEY = os.environ.get("CH_API_KEY")
BASE_URL = "https://api.company-information.service.gov.uk"

def ch_get(endpoint):
    response = requests.get(
        BASE_URL + endpoint,
        auth=HTTPBasicAuth(CH_API_KEY, "")
    )
    response.raise_for_status()
    return response.json()

@app.route("/rix-credit/company/<company_number>")
def get_company(company_number):
    try:
        return jsonify({
            "company_profile": ch_get(f"/company/{company_number}"),
            "officers": ch_get(f"/company/{company_number}/officers"),
            "pscs": ch_get(f"/company/{company_number}/persons-with-significant-control"),
            "charges": ch_get(f"/company/{company_number}/charges"),
            "filing_history": ch_get(f"/company/{company_number}/filing-history")
        })
    except Exception as e:
        return {"error": str(e)}, 500
