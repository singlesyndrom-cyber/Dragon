"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Mana from "@/components/Mana";
import WotcNotice from "@/components/WotcNotice";
import { api } from "@/lib/api";
import { dateOnly } from "@/lib/format";

export default function Cards() {
  const [q, setQ] = useState("");
  const [game, setGame] = useState("");
  const [items, setItems] = useState<any[] | null>(null);
  const [stats, setStats] = useState<any>(null);

  useEffect(() => { api("/cards/stats").then(setStats).catch(() => {}); }, []);
  useEffect(() => {
    const h = setTimeout(() => {
      const qs = new URLSearchParams({ q, limit: "48" });
      if (game) qs.set("game", game);
      api<any[]>(`/cards?${qs}`).then(setItems).catch(() => setItems([]));
    }, 250);
    return () => clearTimeout(h);
  }, [q, game]);

  const mtg = stats?.games?.mtg;
  return (
    <>
      <h1>База карт</h1>
      {mtg ? (
        <p className="lead">
          {mtg.cards.toLocaleString("ru-RU")} карт Magic: The Gathering, из них {mtg.russian.toLocaleString("ru-RU")} с русским
          названием{stats.scryfall_updated ? `. Обновлено ${dateOnly(stats.scryfall_updated)}` : ""}.
          {stats.games.berserk ? ` «Берсерк»: ${stats.games.berserk.cards.toLocaleString("ru-RU")} карт.` : ""}
        </p>
      ) : null}
      <div className="row inline">
        <input type="search" placeholder="Название по-русски или по-английски" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Поиск карты" style={{ minWidth: 320 }} />
        <select value={game} onChange={(e) => setGame(e.target.value)} aria-label="Игра">
          <option value="">Все игры</option>
          <option value="mtg">Magic: The Gathering</option>
          <option value="berserk">Берсерк</option>
        </select>
      </div>
      {items === null ? <p className="muted section">Загружаем…</p> : items.length ? (
        <div className="grid section">
          {items.map((c) => (
            <Link key={c.id} href={`/cards/${c.id}`} className="tile">
              {c.image_url ? <img src={c.image_url} alt="" loading="lazy" /> : <span className="noimg">{c.name}</span>}
              <span className="cap">
                <b>{c.name_ru || c.name}</b>
                {c.name_ru ? <span className="muted small">{c.name}<br /></span> : null}
                <span className="small"><Mana text={c.mana_cost} size={14} /></span>
              </span>
            </Link>
          ))}
        </div>
      ) : (
        <p className="muted section">
          {mtg ? "Ничего не найдено. Проверьте написание или попробуйте название на другом языке."
            : "База карт ещё загружается: первая загрузка из Scryfall занимает несколько минут после запуска сайта."}
        </p>
      )}
      <WotcNotice />
    </>
  );
}
