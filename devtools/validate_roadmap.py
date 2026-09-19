from pathlib import Path
import re

path = Path("AI_Ayafumi_Gourmet_Roadmap.txt")

if not path.is_file():
    print("[FAIL] Roadmap not found")
    raise SystemExit(1)

text = path.read_text(encoding="utf-8-sig")
errors = []

required = [
    "## 1. 現在地",
    "## 2. Phase一覧",
    "## 3. 未解決・保留",
    "## 4. 次にやること",
    "## 5. 運用ルール",
]

for heading in required:
    if heading not in text:
        errors.append(f"Missing section: {heading}")

if re.search(r"(?m)^#+\s+\d{4}-\d{2}-\d{2}", text):
    errors.append("Date-based work log heading found")

for heading in [
    "調査内容",
    "実施した変更",
    "テスト結果",
    "Git操作",
]:
    if re.search(rf"(?m)^#+\s+.*{re.escape(heading)}.*$", text):
        errors.append(f"WorkLog-only heading found: {heading}")

if errors:
    for error in errors:
        print(f"[FAIL] {error}")
    print("ROADMAP GUARD: FAIL")
    raise SystemExit(1)

print("ROADMAP GUARD: PASS")
