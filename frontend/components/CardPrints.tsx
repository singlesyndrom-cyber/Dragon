"use client";

import Link from "next/link";
import { useState } from "react";
import FlipCard from "@/components/FlipCard";
import { qv, searchHref } from "@/lib/cards";

const RARITY: Record<string, string> = { common: "обычная", uncommon: "необычная", rare: "редкая", mythic: "мифическая", special: "особая", bonus: "бонусная", ultra: "ультраредкая" };

type Print = { id: number; set: string; set_name?: string; number?: string; rarity?: string; released_at?: string;
  artist?: string; image_url?: string; image_large?: string; back_image?: string; prices: Record<string, number>;
  finishes: string[]; promo: boolean; full_art: boolean };

function price(p: Record<string, number> | undefined) {
  if (!p) return "";
  return [p.usd != null && `$${p.usd}`, p.eur != null && `€${p.eur}`].filter(Boolean).join(" · ");
}

/** Картинка и сведения карты с выбором издания: клик по изданию меняет картинку, сет, художника и цену. */
export default function CardPrints({ card, backFallback }: { card: any; backFallback?: string | null }) {
  const prints: Print[] = card.prints || [];
  const [sel, setSel] = useState<Print | null>(prints.find((p) => p.image_url === card.image_url) || prints[0] || null);
  const [all, setAll] = useState(false);
  const x = card.extra || {};
  const img = sel?.image_url || card.image_url;
  const back = sel ? sel.back_image : backFallback;
  const artist = sel?.artist || x.artist;
  const prices = sel ? sel.prices : card.prices || {};
  const shown = all ? prints : prints.slice(0, 12);
  return (
    <>
      <FlipCard front={img} back={back} alt={card.name} className="cardimg" />
      <dl className="facts">
        {(sel?.set_name || card.set_name) ? (
          <><dt>Сет</dt><dd><Link href={searchHref(`s:${sel?.set || card.set}`, card.game)}>{sel?.set_name || card.set_name}</Link>
            {sel?.number ? <span className="muted"> №{sel.number}</span> : null}</dd></>
        ) : null}
        {(sel?.rarity || card.rarity) ? (<><dt>Редкость</dt><dd>{RARITY[sel?.rarity || card.rarity] || sel?.rarity || card.rarity}</dd></>) : null}
        {artist ? (<><dt>Художник</dt><dd><Link href={searchHref(`a:${qv(artist)}`, card.game)}>{artist}</Link></dd></>) : null}
        {prices.usd != null || prices.eur != null ? (
          <><dt>Цена</dt><dd className="num">{price(prices)}
            {prices.usd_foil != null ? <span className="muted"> (фойл ${prices.usd_foil})</span> : null}</dd></>
        ) : null}
      </dl>
      {prints.length > 1 ? (
        <section>
          <h3 style={{ marginBottom: 6 }}>Издания <span className="muted small">{prints.length}</span></h3>
          <ul className="prints">
            {shown.map((p) => (
              <li key={p.id}>
                <button type="button" className={sel?.id === p.id ? "on" : ""} onClick={() => setSel(p)}
                  title={`${p.set_name || p.set}${p.number ? ` №${p.number}` : ""}`}>
                  <span className="pset">{p.set.toUpperCase()}</span>
                  <span className="pname">{p.set_name}{p.promo ? " · промо" : ""}{p.full_art ? " · full art" : ""}
                    {p.finishes?.includes("etched") ? " · etched" : ""}</span>
                  <span className="muted small">{p.released_at ? p.released_at.slice(0, 4) : ""}</span>
                  <span className="num small">{p.prices?.usd != null ? `$${p.prices.usd}` : ""}</span>
                </button>
              </li>
            ))}
          </ul>
          {prints.length > 12 ? (
            <button type="button" className="link-btn small" onClick={() => setAll(!all)}>{all ? "Свернуть" : `Показать все ${prints.length}`}</button>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
