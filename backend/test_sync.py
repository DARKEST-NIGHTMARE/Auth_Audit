import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("CEREBRAS_API_KEY")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

payload = {
    "model": "llama3.1-8b",
    "messages": [
        {"role": "system", "content": "You are a legal assistant."},
        {"role": "user", "content": "Who is Markandey Katju?"}
    ],
    "temperature": 0.1,
    "max_tokens": 1024,
}

print("Sending request to Cerebras...")
response = requests.post("https://api.cerebras.ai/v1/chat/completions", headers=headers, json=payload)
print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.text}")
