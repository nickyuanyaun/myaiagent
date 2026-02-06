
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY") # User said they use this env var for the key

print(f"Checking models with key: {api_key[:5]}...")

client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})

try:
    print("\n--- Introspecting client.models ---")
    print(dir(client.models))
    
    print("\n--- Attempting List ---")
    # Trying common variations based on introspection guess
    if hasattr(client.models, 'list'):
        for m in client.models.list():
             print(f"Name: {m.name}")
             # print(f"Supported Generation Methods: {m.supported_generation_methods}") # specific attr might vary
             print("-" * 10)
    elif hasattr(client.models, 'list_models'):
         # We already know this failed but just in case
         pass
except Exception as e:
    print(f"Error introspecting/listing: {e}")
