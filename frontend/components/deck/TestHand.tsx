"use client";

import { useState } from "react";
import FlipCard from "@/components/FlipCard";
import { Row, shuffle } from "@/lib/decks";

type C = { uid: number; name: string; image?: string | null; back?: string | null };

/** Тестовая рука: перемешать основную колоду (без командира и сайда), взять 7, муллиган, добор.
 *  «Берсерк»: раздача (size карт) для сбора отряда, без муллигана. */
export default function TestHand({ rows, lang, size: handSize = 7, berserk = false }: {
  rows: Row[]; lang: "ru" | "en"; size?: number; berserk?: boolean;
}) {
  const [library, setLibrary] = useState<C[]>([]);
  const [hand, setHand] = useState<C[]>([]);
  const [mulligans, setMulligans] = useState(0);

  function fresh(): C[] {
    const cards: C[] = [];
    let uid = 0;
    for (const r of rows.filter((x) => x.section === "main")) {
      for (let i = 0; i < r.qty; i++) {
        cards.push({ uid: uid++, name: lang === "ru" ? r.card?.name_ru || r.name : r.name, image: r.card?.image_url, back: r.card?.back_image });
      }
    }
    return shuffle(cards);
  }
  function deal(mull: number) {
    const lib = fresh();
    setHand(lib.slice(0, handSize));
    setLibrary(lib.slice(handSize));
    setMulligans(mull);
  }
  function draw() {
    if (!library.length) return;
    setHand([...hand, library[0]]);
    setLibrary(library.slice(1));
  }

  const size = rows.filter((x) => x.section === "main").reduce((n, r) => n + r.qty, 0);
  if (size < handSize) return <p className="muted small">Для тестовой {berserk ? "раздачи" : "руки"} нужно хотя бы {handSize} карт в колоде.</p>;
  return (
    <div>
      <div className="row">
        <button type="button" className="primary" onClick={() => deal(0)}>{hand.length ? (berserk ? "Новая раздача" : "Новая рука") : `Взять ${handSize} карт`}</button>
        {hand.length ? (
          <>
            {berserk ? null : <button type="button" onClick={() => deal(mulligans + 1)}>Муллиган</button>}
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
            ? <FlipCard key={c.uid} front={c.image} back={c.back} alt={c.name} />
            : <span key={c.uid} className="noimg">{c.name}</span>)}
        </div>
      ) : null}
    </div>
  );
}
