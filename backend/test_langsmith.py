import os
from dotenv import load_dotenv

# Load env
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

print(f"Checking environment variables from: {ENV_FILE}")
print(f"LANGCHAIN_TRACING_V2: {os.environ.get('LANGCHAIN_TRACING_V2')}")
print(f"LANGCHAIN_PROJECT: {os.environ.get('LANGCHAIN_PROJECT')}")
print(f"LANGCHAIN_API_KEY: {os.environ.get('LANGCHAIN_API_KEY')[:10]}... (masked)")

try:
    from langsmith import traceable
    from langsmith import Client
    
    client = Client()
    print("✅ LangSmith Client initialized successfully.")
    
    @traceable(name="Independence Test")
    def test_trace():
        return "Trace successful"

    print("🚀 Sending test trace...")
    res = test_trace()
    print(f"Result: {res}")
    print("✅ Test trace sent. Please check your LangSmith dashboard.")

except Exception as e:
    print(f"❌ Error: {e}")
