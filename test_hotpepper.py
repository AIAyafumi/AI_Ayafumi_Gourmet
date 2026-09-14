import os
import requests

key = os.getenv("HOTPEPPER_API_KEY")

api_url = "https://webservice.recruit.co.jp/hotpepper/gourmet/v1/"

params = {
    "key": key,
    "keyword": "八王子 ラーメン",
    "format": "json",
    "count": 10,
}

response = requests.get(api_url, params=params)

print("HTTP:", response.status_code)

data = response.json()
results = data["results"]

print("検索件数:", results["results_available"])
print("取得件数:", results["results_returned"])
print()

print("========================================")
print("Hot Pepper 店舗候補")
print("========================================")
print()

for i, shop in enumerate(results.get("shop", []), 1):

    name = shop.get("name", "")
    address = shop.get("address", "")
    station = shop.get("station_name", "")
    budget = shop.get("budget", {}).get("average", "")
    url_pc = shop.get("urls", {}).get("pc", "")
    genre = shop.get("genre", {}).get("name", "")
    lunch = shop.get("lunch", "")

    print(f"{i}. {name}")
    print(f"   ジャンル: {genre}")
    print(f"   住所: {address}")
    print(f"   駅: {station}")
    print(f"   予算: {budget}")
    print(f"   ランチ: {lunch}")
    print(f"   Hot Pepper: {url_pc}")

    # ----------------------------------------
    # Hot Pepper店舗ページを確認
    # ----------------------------------------

    try:
        page = requests.get(
            url_pc,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        page_text = page.text

        closed_words = [
            "閉店",
            "閉店しました",
            "閉店のお知らせ",
            "営業終了",
            "閉業"
        ]

        found_closed_word = None

        for word in closed_words:
            if word in page_text:
                found_closed_word = word
                break

        if found_closed_word:
            print(f"   判定: ❌ 閉店の可能性あり（「{found_closed_word}」を検出）")
        else:
            print("   判定: 🟡 Hot Pepper上では閉店表示なし")

    except Exception as e:
        print(f"   判定: ⚠️ チェック失敗 ({e})")

    print()

print("========================================")
print("チェック終了")
print("========================================")