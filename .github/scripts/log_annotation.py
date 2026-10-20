"""Выводит хвост лога сборки как аннотацию GitHub (логи Actions не всегда доступны снаружи)."""
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
text = re.sub(r"\x1b\[[0-9;]*m", "", text)
lines = text.splitlines()
idx = [i for i, l in enumerate(lines) if re.search(r"(?i)(type error|error|failed to compile|module not found)", l)]
start = max(0, idx[0] - 5) if idx else max(0, len(lines) - 60)
chunk = "\n".join(lines[start:start + 80])[:3800]
print("::error title=build::" + chunk.replace("%", "%25").replace("\n", "%0A"))
