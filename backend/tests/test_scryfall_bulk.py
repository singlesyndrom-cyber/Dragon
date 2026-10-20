import gzip
import json
import os
import tempfile

import pytest

from app.scryfall import bulk_url, iter_bulk

CARDS = [{"oracle_id": "a", "name": "Sol Ring"}, {"oracle_id": "b", "name": "Арбор"}]


def _write(data: bytes) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def test_jsonl_gzip_new_format():
    path = _write(gzip.compress("\n".join(json.dumps(c, ensure_ascii=False) for c in CARDS).encode() + b"\n"))
    assert list(iter_bulk(path)) == CARDS


def test_jsonl_plain_and_blank_lines():
    path = _write(("\n" + "\n\n".join(json.dumps(c, ensure_ascii=False) for c in CARDS) + "\n").encode())
    assert list(iter_bulk(path)) == CARDS


def test_json_array_old_format():
    pytest.importorskip("ijson")
    path = _write(json.dumps(CARDS, ensure_ascii=False).encode())
    assert list(iter_bulk(path)) == CARDS
    gz = _write(gzip.compress(json.dumps(CARDS).encode()))
    assert list(iter_bulk(gz)) == CARDS


def test_bulk_url_both_formats():
    new = {"data": [{"type": "oracle_cards", "jsonl_download_uri": "https://d/o.jsonl.gz"}]}
    old = {"data": [{"type": "default_cards", "download_uri": "x"}, {"type": "oracle_cards", "download_uri": "https://d/o.json"}]}
    assert bulk_url(new) == "https://d/o.jsonl.gz" and bulk_url(old) == "https://d/o.json"
    with pytest.raises(ValueError, match="нет ссылки"):
        bulk_url({"data": [{"type": "oracle_cards", "name": "x"}]})
    with pytest.raises(ValueError, match="не отдал"):
        bulk_url({"data": []})
