"""Проверка на настоящем Scryfall: структура ответов совпадает с тем, что ожидает наш разбор."""
import re
import sys
import time

import httpx

sys.path.insert(0, "backend")
from app.cardimport import normalize_ru, normalize_scryfall  # noqa: E402
from app.scryfall import API, HEADERS  # noqa: E402

with httpx.Client(headers=HEADERS, timeout=30) as c:
    bulk = c.get(f"{API}/bulk-data").raise_for_status().json()
    oracle = next(x for x in bulk["data"] if x["type"] == "oracle_cards")
    time.sleep(0.2)
    card = normalize_scryfall(c.get(f"{API}/cards/named", params={"exact": "Sol Ring"}).raise_for_status().json())
    time.sleep(0.2)
    dfc = normalize_scryfall(c.get(f"{API}/cards/named", params={"exact": "Delver of Secrets"}).raise_for_status().json())
    time.sleep(0.2)
    page = c.get(f"{API}/cards/search", params={"q": "lang:ru", "unique": "cards", "order": "name"}).raise_for_status().json()

ru = [r for r in (normalize_ru(o) for o in page["data"]) if r]
assert card and card["legalities"].get("commander") == "legal" and card["image_url"], card
assert card["prices"], "нет цен"
assert dfc and len(dfc["extra"]["faces"]) == 2 and dfc["image_url"], dfc
assert len(ru) > 100 and all(re.search("[а-яё]", r["name_ru"], re.I) for r in ru[:20]), ru[:3]
assert page.get("has_more") and page.get("next_page")
print(f"::notice title=scryfall::oracle_cards обновлён {oracle.get('updated_at', '?')[:10]}; русских на 1-й странице {len(ru)} "
      f"(всего {page.get('total_cards')}), пример: {ru[0]['name_ru']}; Sol Ring ${card['prices'].get('usd')}")
