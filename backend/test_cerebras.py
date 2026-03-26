import asyncio
import os
import sys

# Add backend dir to path to import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.summarization.ai_clients import generate_text

async def main():
    try:
        print("Sending test generation request to Cerebras...")
        # Sending a large prompt to see if it overflows, or just a simple one to test the model name
        res = await generate_text("Who is Markandey Katju in the context of Indian law?", "You are a legal assistant.")
        print("\nSUCCESS\n", res)
    except Exception as e:
        print("\nFAILURE\n", e)

if __name__ == "__main__":
    asyncio.run(main())
