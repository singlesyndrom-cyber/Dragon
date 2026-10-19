"""Превращает результаты pytest (junit.xml) в аннотации GitHub: так ошибки видны без скачивания логов."""
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else list(root)
total = fails = skipped = 0
for suite in suites:
    for case in suite.iter("testcase"):
        total += 1
        if case.find("skipped") is not None:
            skipped += 1
        for tag in ("failure", "error"):
            node = case.find(tag)
            if node is not None:
                fails += 1
                text = ((node.get("message") or "") + "\n" + (node.text or ""))[-3500:]
                print(f"::error title={case.get('name')}::{esc(text)}")
print(f"::notice title=pytest::всего {total}, упало {fails}, пропущено {skipped}")
