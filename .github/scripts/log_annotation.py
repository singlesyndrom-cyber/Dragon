"""Выводит суть лога (без шума docker pull/build) как аннотацию GitHub."""
import re
import sys

NOISE = re.compile(r"(Extracting|Pull complete|Downloading|Download complete|Waiting|Verifying|Pulling fs|Already exists"
                   r"|Container |Network |Volume |^#\d+ |Digest:|Status:|Pulled$)")
text = re.sub(r"\x1b\[[0-9;]*m", "", open(sys.argv[1], encoding="utf-8", errors="replace").read())
lines = [l for l in text.splitlines() if l.strip() and not NOISE.search(l)]
idx = [i for i, l in enumerate(lines) if re.search(r"(?i)(ПРОВЕРКА НЕ ПРОШЛА|FAIL|Traceback|type error|failed to compile"
                                                     r"|module not found|POST .* -> \d|error)", l)]
start = max(0, idx[0] - 5) if idx else max(0, len(lines) - 60)
chunk = "\n".join(lines[start:start + 90])[:3800]
print("::error title=build::" + chunk.replace("%", "%25").replace("\n", "%0A"))
