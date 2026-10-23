"use client";

import { useState } from "react";
import { Row, shuffle } from "@/lib/decks";

type C = { uid: number; name: string; image?: string | null };

/** Тестовая рука: перемешать основную колоду (без командира и сайда), взять 7, муллиган, добор. */
export default function TestHand({ rows, lang }: { rows: Row[]; lang: "ru" | "en" }) {
  const [library, setLibrary] = useState<C[]>([]);
  const [hand, setHand] = useState<C[]>([]);
  const [mulligans, setMulligans] = useState(0);

  function fresh(): C[] {
    const cards: C[] = [];
    let uid = 0;
    for (const r of rows.filter((x) => x.section === "main")) {
      for (let i = 0; i < r.qty; i++) {
        cards.push({ uid: uid++, name: lang === "ru" ? r.card?.name_ru || r.name : r.name, image: r.card?.image_url });
      }
    }
    return shuffle(cards);
  }
  function deal(mull: number) {
    const lib = fresh();
    setHand(lib.slice(0, 7));
    setLibrary(lib.slice(7));
    setMulligans(mull);
  }
  function draw() {
    if (!library.length) return;
    setHand([...hand, library[0]]);
    setLibrary(library.slice(1));
  }

  const size = rows.filter((x) => x.section === "main").reduce((n, r) => n + r.qty, 0);
  if (size < 7) return <p className="muted small">Для тестовой руки нужно хотя бы 7 карт в основной колоде.</p>;
  return (
    <div>
      <div className="row">
        <button type="button" className="primary" onClick={() => deal(0)}>{hand.length ? "Новая рука" : "Взять 7 карт"}</button>
        {hand.length ? (
          <>
            <button type="button" onClick={() => deal(mulligans + 1)}>Муллиган</button>
            <button type="button" onClick={draw} disabled={!library.length}>Взять карту</button>
            <span className="muted small">
              {mulligans ? `Муллиганов: ${mulligans} — по лондонскому правилу положите ${mulligans} ${mulligans === 1 ? "карту" : "карты"} вниз. ` : ""}
              В библиотеке {library.length}
            </span>
          </>
        ) : null}
      </div>
      {hand.length ? (
        <div className="hand section">
          {hand.map((c) => c.image
            ? <img key={c.uid} src={c.image} alt={c.name} title={c.name} />
            : <span key={c.uid} className="noimg">{c.name}</span>)}
        </div>
      ) : null}
    </div>
  );
}
