"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Cards() {
  const [q, setQ] = useState("");
  const [game, setGame] = useState("");
  const [items, setItems] = useState<any[] | null>(null);
  const [open, setOpen] = useState<any>(null);

  useEffect(() => {
    const h = setTimeout(() => {
      const qs = new URLSearchParams({ q, limit: "48" });
      if (game) qs.set("game", game);
      api<any[]>(`/cards?${qs}`).then(setItems).catch(() => setItems([]));
    }, 250);
    return () => clearTimeout(h);
  }, [q, game]);

  return (
    <>
      <h1>База карт</h1>
      <div className="row inline">
        <input type="search" placeholder="Название карты" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Поиск карты" />
        <select value={game} onChange={(e) => setGame(e.target.value)} aria-label="Игра">
          <option value="">Все игры</option>
          <option value="mtg">Magic: The Gathering</option>
          <option value="berserk">Берсерк</option>
        </select>
      </div>
      {open ? (
        <div className="panel section split">
          <div>
            <h2 style={{ marginTop: 0 }}>{open.name}</h2>
            <dl className="facts">
              {open.type ? (<><dt>Тип</dt><dd>{open.type}</dd></>) : null}
              {open.mana_cost ? (<><dt>Стоимость</dt><dd>{open.mana_cost}</dd></>) : null}
              {open.set ? (<><dt>Сет</dt><dd>{open.set_name || open.set}</dd></>) : null}
              {open.rarity ? (<><dt>Редкость</dt><dd>{open.rarity}</dd></>) : null}
            </dl>
            {open.text ? <p style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>{open.text}</p> : null}
            <button onClick={() => setOpen(null)}>Закрыть</button>
          </div>
          {open.image_url ? <img src={open.image_url} alt={open.name} style={{ width: "100%", maxWidth: 320, borderRadius: 12 }} /> : null}
        </div>
      ) : null}
      {items === null ? <p className="muted section">Загружаем…</p> : items.length ? (
        <div className="grid section">
          {items.map((c) => (
            <button key={c.id} className="tile" style={{ padding: 0, textAlign: "left", border: "none" }}
              onClick={() => api(`/cards/${c.id}`).then(setOpen)}>
              {c.image_url ? <img src={c.image_url} alt="" loading="lazy" /> : <span className="noimg">{c.name}</span>}
              <span className="cap"><b>{c.name}</b><span className="muted small">{c.type || ""}</span></span>
            </button>
          ))}
        </div>
      ) : <p className="muted section">Ничего не найдено. Если базы ещё нет, администратор загрузит её в админке.</p>}
    </>
  );
}
