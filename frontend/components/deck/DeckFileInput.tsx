"use client";

import { useState } from "react";

/** Имя колоды из имени файла: «better-then-you-20240530-072223.txt» -> «Better then you». */
export function nameFromFile(file: string): string {
  const base = file.replace(/\.[^.]+$/, "").replace(/[-_ ]?\d{8}[-_ ]?\d{6}$/, "").replace(/[-_]+/g, " ").trim();
  return base ? base[0].toUpperCase() + base.slice(1) : "";
}

/** Загрузка списка колоды из файла (.txt, .dec, .dck): экспорт Moxfield, MTGGoldfish, Arena, MTGO. */
export default function DeckFileInput({ onText }: { onText: (text: string, name: string) => void }) {
  const [err, setErr] = useState("");
  return (
    <span className="row" style={{ gap: 8 }}>
      <label className="btn" style={{ margin: 0, cursor: "pointer", display: "inline-flex", alignItems: "center" }}>
        Выбрать файл .txt
        <input type="file" accept=".txt,.dec,.dck,.dek,text/plain" style={{ display: "none" }} onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (!f) return;
          setErr("");
          if (f.size > 200_000) { setErr("Файл слишком большой для списка колоды"); return; }
          try {
            onText(await f.text(), nameFromFile(f.name));
          } catch {
            setErr("Не удалось прочитать файл");
          }
        }} />
      </label>
      {err ? <span className="err small">{err}</span> : null}
    </span>
  );
}
