"""Слаги для статей и теги (чистая логика)."""
import re

_RU = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))


def slugify(text: str, max_len: int = 80, fallback: str = "post") -> str:
    s = "".join(_RU.get(ch, ch) for ch in text.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:max_len].strip("-")
    return s or fallback


def normalize_tags(tags: list[str], limit: int = 8) -> list[tuple[str, str]]:
    """[(отображаемое имя в нижнем регистре, slug)], без дублей и пустых, не больше limit."""
    out, seen = [], set()
    for t in tags:
        name = re.sub(r"\s+", " ", t).strip().lstrip("#").strip().lower()[:32]
        if not name:
            continue
        slug = slugify(name, 40, fallback="")
        if slug and slug not in seen:
            seen.add(slug)
            out.append((name, slug))
    return out[:limit]
