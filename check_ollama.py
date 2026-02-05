
import asyncio
from openai import AsyncOpenAI
import sys

# Simple test to check if we can connect to a local OpenAI-compatible endpoint (like Ollama or LM Studio)
# or just check if the port is open.

async def check_ollama():
    print("Checking Ollama connection...")
    try:
        # Ollama usually runs on 11434
        # We can use standard HTTP to check
        import urllib.request
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags") as response:
                if response.status == 200:
                    print("✅ Ollama is reachable via HTTP.")
                    print(response.read().decode('utf-8')[:200] + "...") # Print first 200 chars
                    return True
        except Exception as e:
            print(f"❌ HTTP request to Ollama failed: {e}")
            return False

    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(check_ollama())
