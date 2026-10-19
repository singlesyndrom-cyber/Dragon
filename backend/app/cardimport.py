"""Нормализация карт из разных источников в единую схему (без БД, тестируется отдельно)."""
import hashlib
import json
import re
from typing import Any

CANON = ("external_id", "name", "set_code", "set_name", "type_line", "mana_cost", "text", "rarity", "image_url")
LIMITS = {"external_id": 64, "name": 255, "set_code": 16, "set_name": 128, "type_line": 255,
          "mana_cost": 64, "rarity": 32, "image_url": 512}

# Угадывание полей произвольного JSON (для «Берсерка»). Можно переопределить параметром mapping.
ALIASES = {
    "external_id": ["id", "external_id", "card_id", "uid", "code", "number", "код", "номер"],
    "name": ["name", "title", "card_name", "название", "имя"],
    "set_code": ["set", "set_code", "setcode", "expansion", "сет", "издание", "код_сета"],
    "set_name": ["set_name", "setname", "название_сета", "название_издания"],
    "type_line": ["type", "type_line", "types", "card_type", "тип"],
    "mana_cost": ["mana_cost", "manacost", "cost", "стоимость", "цена"],
    "text": ["text", "oracle_text", "description", "effect", "ability", "текст", "описание", "эффект"],
    "rarity": ["rarity", "редкость"],
    "image_url": ["image_url", "image", "img", "picture", "imageurl", "картинка", "изображение"],
}


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()


def front_face(s: str) -> str:
    return s.split(" // ")[0]


def _to_str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _finalize(card: dict, game: str) -> dict:
    name = card["name"]
    card["game"] = game
    card["name_lower"] = norm_name(name)[:255]
    card["name_front"] = norm_name(front_face(name))[:255]
    for k, n in LIMITS.items():
        if card.get(k):
            card[k] = card[k][:n]
    for k in CANON:
        card.setdefault(k, None)
    card.setdefault("cmc", None)
    card.setdefault("commander_legal", None)
    card.setdefault("is_game_changer", False)
    card.setdefault("extra", {})
    return card


def extract_rows(data: Any) -> list[dict]:
    """Принимает массив или объект вида {"cards": [...]} / {"data": [...]}."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("cards", "data", "items", "результаты"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
    return []


def normalize_generic(row: dict, mapping: dict | None = None, game: str = "berserk") -> dict | None:
    lower = {str(k).lower(): k for k in row}
    out: dict = {}
    used: set = set()
    for canon in CANON:
        key = None
        if mapping and mapping.get(canon) in row:
            key = mapping[canon]
        else:
            key = next((lower[a] for a in ALIASES[canon] if a in lower), None)
        if key is not None:
            used.add(key)
            out[canon] = _to_str(row[key])
    if not out.get("name"):
        return None
    if not out.get("external_id"):
        out["external_id"] = hashlib.sha1(f"{out.get('set_code')}|{out['name']}".encode()).hexdigest()
    out["extra"] = {k: v for k, v in row.items() if k not in used}
    return _finalize(out, game)


def normalize_scryfall(obj: dict) -> dict | None:
    if not obj.get("oracle_id") or obj.get("layout") in ("token", "double_faced_token", "emblem", "art_series"):
        return None
    faces = obj.get("card_faces") or []
    f0 = faces[0] if faces else {}
    image = (obj.get("image_uris") or f0.get("image_uris") or {}).get("normal")
    text = obj.get("oracle_text") or "\n//\n".join(f.get("oracle_text", "") for f in faces) or None
    legal = (obj.get("legalities") or {}).get("commander")
    card = {
        "external_id": obj["oracle_id"], "name": obj["name"], "set_code": obj.get("set"),
        "set_name": obj.get("set_name"), "type_line": obj.get("type_line") or f0.get("type_line"),
        "mana_cost": obj.get("mana_cost") or f0.get("mana_cost") or None, "text": text,
        "rarity": obj.get("rarity"), "image_url": image,
        "cmc": float(obj["cmc"]) if obj.get("cmc") is not None else None,
        "commander_legal": None if legal is None else legal == "legal",
        "is_game_changer": bool(obj.get("game_changer", False)),
        "extra": {"color_identity": obj.get("color_identity", [])},
    }
    return _finalize(card, "mtg")
