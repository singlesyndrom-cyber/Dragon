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
    card.setdefault("legalities", {})
    card.setdefault("prices", {})
    card.setdefault("scryfall_uri", None)
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


LEGAL_FORMATS = ("commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "duel", "brawl")


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_scryfall(obj: dict) -> dict | None:
    """Карта из bulk-файла Scryfall «Oracle Cards» (одна запись на карту, а не на печать)."""
    if not obj.get("oracle_id") or obj.get("layout") in ("token", "double_faced_token", "emblem", "art_series"):
        return None
    faces = obj.get("card_faces") or []
    f0 = faces[0] if faces else {}
    uris = obj.get("image_uris") or f0.get("image_uris") or {}
    text = obj.get("oracle_text") or "\n//\n".join(f.get("oracle_text", "") for f in faces) or None
    legal_all = obj.get("legalities") or {}
    legal = legal_all.get("commander")
    prices = obj.get("prices") or {}
    card = {
        "external_id": obj["oracle_id"], "name": obj["name"], "set_code": obj.get("set"),
        "set_name": obj.get("set_name"), "type_line": obj.get("type_line") or f0.get("type_line"),
        "mana_cost": obj.get("mana_cost") or f0.get("mana_cost") or None, "text": text,
        "rarity": obj.get("rarity"), "image_url": uris.get("normal"),
        "cmc": float(obj["cmc"]) if obj.get("cmc") is not None else None,
        "commander_legal": None if legal is None else legal == "legal",
        "is_game_changer": bool(obj.get("game_changer", False)),
        "legalities": {f: legal_all[f] for f in LEGAL_FORMATS if f in legal_all},
        "prices": {k: _num(prices.get(k)) for k in ("usd", "usd_foil", "eur") if _num(prices.get(k)) is not None},
        "scryfall_uri": (obj.get("scryfall_uri") or "")[:512] or None,
        "extra": {"color_identity": obj.get("color_identity", []), "colors": obj.get("colors") or f0.get("colors") or [],
                  "keywords": obj.get("keywords", []), "artist": obj.get("artist") or f0.get("artist"),
                  "power": obj.get("power") or f0.get("power"), "toughness": obj.get("toughness") or f0.get("toughness"),
                  "loyalty": obj.get("loyalty") or f0.get("loyalty"),
                  "image_large": uris.get("large"),
                  "faces": [{"name": f.get("name"), "mana_cost": f.get("mana_cost"), "type_line": f.get("type_line"),
                             "text": f.get("oracle_text"), "image": (f.get("image_uris") or {}).get("normal")}
                            for f in faces] if len(faces) > 1 else []},
    }
    return _finalize(card, "mtg")


def normalize_ru(obj: dict) -> dict | None:
    """Русская печать карты из поиска Scryfall (lang:ru): печатное название, тип и текст.
    Привязка к нашей карте - по oracle_id."""
    if obj.get("lang") != "ru" or not obj.get("oracle_id"):
        return None
    faces = obj.get("card_faces") or []
    name = obj.get("printed_name") or " // ".join(f.get("printed_name") or "" for f in faces).strip(" /")
    if not name:
        return None
    type_ru = obj.get("printed_type_line") or " // ".join(f.get("printed_type_line") or "" for f in faces).strip(" /")
    text_ru = obj.get("printed_text") or "\n//\n".join(f.get("printed_text") or "" for f in faces).strip("\n/")
    return {"oracle_id": obj["oracle_id"], "name_ru": name[:255], "name_ru_lower": norm_name(name)[:255],
            "name_ru_front": norm_name(front_face(name))[:255],
            "type_ru": (type_ru or None) and type_ru[:255], "text_ru": text_ru or None}
