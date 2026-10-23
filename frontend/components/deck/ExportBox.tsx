"use client";

import { useState } from "react";
import { Row, exportText } from "@/lib/decks";

/** Экспорт списка: текст для Moxfield / MTGGoldfish / Arena или MTGO; копировать или скачать .txt. */
export default function ExportBox({ rows, name }: { rows: Row[]; name: string }) {
  const bk = rows.some((r) => r.card?.bk);
  const [style, setStyle] = useState<"text" | "mtgo" | "nxt">(bk ? "nxt" : "text");
  const [copied, setCopied] = useState(false);
  const [prints, setPrints] = useState(true);
  const hasPrints = rows.some((r) => r.card?.print);
  const text = exportText(rows, style, prints);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  }
  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name.replace(/[\\/:*?"<>|]+/g, " ").trim() || "deck"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div>
      <div className="row">
        <select value={style} onChange={(e) => setStyle(e.target.value as any)} aria-label="Формат экспорта" style={{ width: "auto" }}>
          {bk ? (
            <>
              <option value="nxt">NXT (коды карт)</option>
              <option value="mtgo">Список «3 Название»</option>
            </>
          ) : (
            <>
              <option value="text">Moxfield, MTGGoldfish, Arena</option>
              <option value="mtgo">MTGO</option>
            </>
          )}
        </select>
        {style === "text" && hasPrints ? (
          <label className="check" style={{ margin: 0 }}>
            <input type="checkbox" checked={prints} onChange={(e) => setPrints(e.target.checked)} />
            <span>с изданиями</span>
          </label>
        ) : null}
        <button type="button" onClick={copy}>{copied ? "Скопировано" : "Копировать"}</button>
        <button type="button" onClick={download}>Скачать .txt</button>
      </div>
      <textarea readOnly value={text} rows={10} className="section" style={{ marginTop: 12, fontFamily: "monospace" }}
        aria-label="Список колоды" onFocus={(e) => e.currentTarget.select()} />
    </div>
  );
}
