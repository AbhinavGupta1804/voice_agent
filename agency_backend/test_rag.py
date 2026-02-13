import requests
import json

# Local URL for the tool endpoint
url = "http://localhost:8000/api/elevenlabs/product-lookup"

# Test queries
queries = [
    "What are the ingredients in Mango ice cream?",
    "Do you have any sugar free options?",
    "What is the price of Tender Coconut?"
]

print("--- Testing RAG Tool Endpoint ---")

for query in queries:
    print(f"\nQuery: {query}")
    try:
        response = requests.post(
            url, 
            json={"query": query},
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success! Response:")
            print(f"'{data['response']}'")
        else:
            print(f"❌ Error {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        print("Make sure your uvicorn server is running!")
