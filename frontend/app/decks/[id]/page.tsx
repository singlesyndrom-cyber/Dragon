"use client";

import { use, useEffect, useState } from "react";
import Guard from "@/components/Guard";
import { api } from "@/lib/api";

const SECTION: Record<string, string> = { commander: "Командир", main: "Основная колода", side: "Сайдборд" };

export default function DeckPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Deck id={id} /></Guard>;
}

function Deck({ id }: { id: string }) {
  const [d, setD] = useState<any>(undefined);
  useEffect(() => { api(`/decks/${id}`).then(setD).catch(() => setD(null)); }, [id]);
  if (d === undefined) return <p className="muted">Загружаем…</p>;
  if (!d) return <p>Колода не найдена или недоступна. Деклист видят владелец и организаторы турнира, на который он подан.</p>;
  const groups = ["commander", "main", "side"].map((s) => [s, d.cards.filter((c: any) => c.section === s)] as const);
  return (
    <>
      <h1>{d.name}</h1>
      {groups.filter(([, cs]) => cs.length).map(([s, cs]) => (
        <section key={s}>
          <h2>{SECTION[s]} <span className="muted small">{cs.reduce((n: number, c: any) => n + c.qty, 0)}</span></h2>
          <ul className="news-list">
            {cs.map((c: any, i: number) => (
              <li key={i} style={{ padding: "6px 0" }}>
                <span className="num">{c.qty}</span> {c.name}
                {!c.matched ? <span className="loss small"> не найдена в базе</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
