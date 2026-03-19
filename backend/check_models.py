import requests
import os
from dotenv import load_dotenv

load_dotenv("/home/manmath/Documents/OAuth dummy/Login Auth Audit/backend/.env")
api_key = os.getenv("GEMINI_API_KEY")

test_models = ["models/text-embedding-004", "models/embedding-001", "models/gemini-embedding-001"]

for model in test_models:
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:embedContent?key={api_key}"
    payload = {
        "model": model,
        "content": {"parts": [{"text": "Hello world"}]}
    }
    if "004" in model:
        payload["taskType"] = "RETRIEVAL_DOCUMENT"

    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            dim = len(res.json()["embedding"]["values"])
            print(f"SUCCESS: {model} is available and has dimension: {dim}")
        else:
            print(f"FAIL: {model} failed with {res.status_code}: {res.text}")
    except Exception as e:
        print(f"ERROR: {model} exception: {e}")
