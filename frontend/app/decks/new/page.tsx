"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Status, useAction } from "@/components/Form";
import DeckFileInput from "@/components/deck/DeckFileInput";
import Guard from "@/components/Guard";
import { api } from "@/lib/api";
import { DECK_FORMATS, VISIBILITY } from "@/lib/decks";

export default function NewDeckPage() {
  return <Guard><NewDeck /></Guard>;
}

function NewDeck() {
  const router = useRouter();
  const [f, setF] = useState({ name: "", game: "mtg", format: "commander", visibility: "private", text: "", in_meta: false });
  const [open, setOpen] = useState(false);
  const { busy, error, run } = useAction();
  return (
    <>
      <h1>Новая колода</h1>
      <p className="lead">Соберите колоду в конструкторе с поиском карт или вставьте готовый список — его можно будет доработать.</p>
      <form className="stack" style={{ maxWidth: 720 }} onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const body: any = { name: f.name, game: f.game, text: f.text, in_meta: f.in_meta };
          Object.assign(body, { format: f.game === "mtg" ? f.format : "berserk", visibility: f.visibility });
          const r = await api<any>("/decks", { body });
          router.push(`/decks/${r.id}/edit`);
        });
      }}>
        <label><span>Название</span><input required maxLength={128} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })}
          placeholder="Например: Атракса, +1/+1 счётчики" /></label>
        <div className="row inline">
          <label><span>Игра</span>
            <select value={f.game} onChange={(e) => setF({ ...f, game: e.target.value })}>
              <option value="mtg">Magic: The Gathering</option>
              <option value="berserk">Берсерк</option>
            </select>
          </label>
          {f.game === "mtg" ? (
              <label><span>Формат</span>
                <select value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}>
                  {DECK_FORMATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </label>
          ) : null}
          <label><span>Доступ</span>
            <select value={f.visibility} onChange={(e) => setF({ ...f, visibility: e.target.value })}>
              {VISIBILITY.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
        </div>
        <p className="hint" style={{ marginTop: 0 }}>{VISIBILITY.find(([k]) => k === f.visibility)?.[2]}.</p>
        <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
          <summary>Загрузить готовый список (необязательно)</summary>
          <div className="row" style={{ marginTop: 12 }}>
            <DeckFileInput onText={(text, name) => { setF((x) => ({ ...x, text, name: x.name || name })); setOpen(true); }} />
            <span className="muted small">или вставьте текст ниже</span>
          </div>
          <label style={{ marginTop: 12 }}><span>{f.game === "mtg" ? "Экспорт из Moxfield, MTGGoldfish, Archidekt, Arena или MTGO; строки вида «1 Sol Ring»" : "Строки вида «3 Преторианец»"}</span>
            <textarea value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} style={{ minHeight: 200 }}
              placeholder={f.game === "mtg" ? "Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n35 Forest" : "3 Преторианец\n2 Изобретатель Братства"} />
          </label>
        </details>
        <label className="check">
          <input type="checkbox" checked={f.in_meta} onChange={(e) => setF({ ...f, in_meta: e.target.checked })} />
          <span>Учитывать в мете — колода анонимно попадёт в «Популярное у игроков»</span>
        </label>
        <div><button className="primary" disabled={busy}>Создать и открыть конструктор</button></div>
        <Status error={error} />
      </form>
    </>
  );
}
