import os
import requests

api_key = os.getenv("TAVILY_API_KEY")

url = "https://api.tavily.com/search"

payload = {
    "api_key": api_key,
    "query": "天下一品 多摩ニュータウン店 閉店",
    "search_depth": "basic",
    "max_results": 5,
}

response = requests.post(
    url,
    json=payload,
    timeout=30
)

print("HTTP:", response.status_code)
print()

if response.status_code != 200:
    print(response.text)
    exit()

data = response.json()

print("========================================")
print("Tavily検索結果")
print("========================================")
print()

for i, result in enumerate(data.get("results", []), 1):
    print(f"{i}. {result.get('title', '')}")
    print(f"   URL: {result.get('url', '')}")
    print(f"   内容: {result.get('content', '')[:500]}")
    print()