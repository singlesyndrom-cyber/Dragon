"use client";

import { useMemo, useState } from "react";
import FlipCard from "@/components/FlipCard";
import type { Bk } from "@/lib/berserk";
import { Row, shuffle } from "@/lib/decks";

/** Тренировка набора отряда «Берсерка» по Расширенным правилам 6.1-1 (п. 402–403):
 *  раздача 15 карт, пересдача за 1 золотой, 24 золотых + 22 серебряных (второй игрок +1/+1),
 *  элитные - только золотом, рядовые - серебром и золотом, штраф 1 золотой за каждую новую стихию кроме первой
 *  (нейтральные - не стихия), без дублей уникальных карт, летающие не дороже 15 кристаллов, не больше 15 карт. */

const DEAL = 15, GOLD = 24, SILVER = 22, FLYERS_MAX = 15, CELLS = 15;
const NEUTRAL = "Нейтральная";

type C = { uid: number; name: string; title: string; image?: string | null; back?: string | null; cost: number;
  elite: boolean; unique: boolean; elements: string[]; flyer: boolean; creature: boolean };

function cardsOf(rows: Row[], lang: "ru" | "en"): C[] {
  const out: C[] = [];
  let uid = 0;
  for (const r of rows.filter((x) => x.section === "main")) {
    const b: Bk = r.card?.bk || {};
    const kind = (b.kind || r.card?.type || "").toLowerCase();
    for (let i = 0; i < r.qty; i++) {
      out.push({ uid: uid++, name: r.name, title: lang === "ru" ? r.card?.name_ru || r.name : r.name,
        image: r.card?.image_url, back: r.card?.back_image, cost: Number(r.card?.mana_cost) || 0,
        elite: !!b.elite, unique: !!b.unique, elements: (b.elements || []).filter((e) => e !== NEUTRAL),
        flyer: kind.includes("летающ"), creature: kind.startsWith("существо") });
    }
  }
  return out;
}

/** Сколько стоит отряд: золото за элитных и штрафы за стихии, рядовые - сначала серебром. */
function bill(squad: C[], gold: number, silver: number) {
  const elite = squad.filter((c) => c.elite).reduce((n, c) => n + c.cost, 0);
  const ordinary = squad.filter((c) => !c.elite).reduce((n, c) => n + c.cost, 0);
  const elements = Array.from(new Set(squad.flatMap((c) => c.elements)));
  const penalty = Math.max(0, elements.length - 1);
  const silverUsed = Math.min(ordinary, silver);
  const goldUsed = elite + penalty + (ordinary - silverUsed);
  const flyers = squad.filter((c) => c.flyer).reduce((n, c) => n + c.cost, 0);
  return { goldUsed, silverUsed, penalty, elements, flyers, ok: goldUsed <= gold };
}

function whyNot(c: C, squad: C[], gold: number, silver: number): string | null {
  if (squad.length >= CELLS) return `В отряде уже ${CELLS} карт — больше нет клеток для расстановки`;
  if ((c.unique || squad.some((s) => s.unique && s.name === c.name)) && squad.some((s) => s.name === c.name)) {
    return "Уникальная карта: вторую с таким названием взять нельзя";
  }
  const b = bill([...squad, c], gold, silver);
  if (b.flyers > FLYERS_MAX) return `Летающих можно набрать не больше чем на ${FLYERS_MAX} кристаллов`;
  if (!b.ok) return c.elite ? "Не хватает золота: элитные карты оплачиваются только золотом" : "Не хватает кристаллов";
  return null;
}

export default function SquadBuilder({ rows, lang }: { rows: Row[]; lang: "ru" | "en" }) {
  const all = useMemo(() => cardsOf(rows, lang), [rows, lang]);
  const [second, setSecond] = useState(false);
  const [redeals, setRedeals] = useState(0);
  const [deal, setDeal] = useState<C[]>([]);
  const [squad, setSquad] = useState<C[]>([]);
  const [msg, setMsg] = useState("");

  const gold = GOLD + (second ? 1 : 0) - redeals;
  const silver = SILVER + (second ? 1 : 0);
  const b = bill(squad, gold, silver);

  function newDeal(redeal: boolean) {
    setDeal(shuffle(all).slice(0, DEAL));
    setSquad([]);
    setMsg("");
    setRedeals(redeal ? redeals + 1 : 0);
  }
  function take(c: C) {
    const why = whyNot(c, squad, gold, silver);
    if (why) { setMsg(`${c.title}: ${why}.`); return; }
    setSquad([...squad, c]);
    setMsg("");
  }

  if (all.length < DEAL) return <p className="muted small">Для раздачи нужно хотя бы {DEAL} карт в колоде.</p>;
  const inSquad = new Set(squad.map((c) => c.uid));
  return (
    <div>
      <div className="row">
        <button type="button" className="primary" onClick={() => newDeal(false)}>{deal.length ? "Новая раздача" : `Раздать ${DEAL} карт`}</button>
        {deal.length ? (
          <button type="button" disabled={gold < 1} onClick={() => newDeal(true)}
            title="Карты возвращаются в колоду, штраф — 1 золотой кристалл">Пересдача (−1 золотой)</button>
        ) : null}
        <label className="check" style={{ margin: 0 }}>
          <input type="checkbox" checked={second} onChange={(e) => setSecond(e.target.checked)} />
          <span>Хожу вторым (+1 золотой, +1 серебряный)</span>
        </label>
      </div>
      {deal.length ? (
        <>
          <div className="row stat-tiles section">
            <div><b className="num">{gold - b.goldUsed}</b><span className="muted small">золотых из {gold}</span></div>
            <div><b className="num">{silver - b.silverUsed}</b><span className="muted small">серебряных из {silver}</span></div>
            <div><b className="num">{squad.length}/{CELLS}</b><span className="muted small">карт в отряде</span></div>
            <div><b className="num">{b.flyers}/{FLYERS_MAX}</b><span className="muted small">на летающих</span></div>
          </div>
          <p className="small" style={{ margin: "4px 0" }}>
            Стихии: {b.elements.length ? b.elements.join(", ") : "—"}{b.penalty ? ` · штраф ${b.penalty} золотых` : ""}
            {redeals ? ` · пересдач: ${redeals}` : ""}
            {squad.length && !squad.some((c) => c.creature) ? <span className="loss"> · в отряде нет ни одного существа</span> : null}
          </p>
          {msg ? <p className="loss small" role="status">{msg}</p> : null}
          <h3>Раздача <span className="muted small">нажмите на карту, чтобы взять её в отряд</span></h3>
          <div className="hand">
            {deal.filter((c) => !inSquad.has(c.uid)).map((c) => (
              <button key={c.uid} type="button" className={`squadcard ${whyNot(c, squad, gold, silver) ? "dim" : ""}`}
                onClick={() => take(c)} title={`${c.title}: ${c.cost} ${c.elite ? "элитная (золото)" : "рядовая"}`}>
                {c.image ? <FlipCard front={c.image} back={c.back} alt={c.title} /> : <span className="noimg">{c.title}</span>}
              </button>
            ))}
          </div>
          <h3>Отряд <span className="muted small">нажмите на карту, чтобы вернуть её в раздачу</span></h3>
          {squad.length ? (
            <div className="hand">
              {squad.map((c) => (
                <button key={c.uid} type="button" className="squadcard" onClick={() => setSquad(squad.filter((x) => x.uid !== c.uid))}
                  title={`Вернуть «${c.title}»`}>
                  {c.image ? <FlipCard front={c.image} back={c.back} alt={c.title} /> : <span className="noimg">{c.title}</span>}
                </button>
              ))}
            </div>
          ) : <p className="muted small">Пока пусто.</p>}
          <p className="muted small">Особенности карт «до набора отряда» и «при наборе в отряд» здесь не учитываются.</p>
        </>
      ) : null}
    </div>
  );
}
