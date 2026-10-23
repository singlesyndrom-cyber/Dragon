"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { CardInfo, Row } from "@/lib/decks";
import { viaSite } from "@/lib/img";

type Print = { id: number; set: string; set_name?: string | null; number?: string | null; released_at?: string | null;
  image_url?: string | null; image_large?: string | null; back_image?: string | null; prices: Record<string, number>;
  promo?: boolean; full_art?: boolean; finishes?: string[] };

/** Окно выбора издания карты для колоды (как «Change printing» на Moxfield): сетка картинок всех изданий. */
export default function PrintPicker({ row, onPick, onClose }: {
  row: Row; onPick: (card: CardInfo) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [data, setData] = useState<any>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  const card = row.card!;

  useEffect(() => {
    ref.current?.showModal();
    api<any>(`/cards/${card.id}`).then(setData).catch((e) => setErr(e.message));
  }, [card.id]);

  const prints: Print[] = data?.prints || [];
  const f = q.trim().toLowerCase();
  const shown = f ? prints.filter((p) => p.set.includes(f) || (p.set_name || "").toLowerCase().includes(f) || p.number === f) : prints;

  function pick(p: Print | null) {
    if (!data) return;
    const base = { ...card, image_url: data.image_url, image_large: data.extra?.image_large ?? null,
      back_image: data.back_image || null, set: data.set, prices: data.prices || {}, print: null };
    if (!p) {
      onPick(base);                       // издание по умолчанию - как в карточке карты
    } else {
      onPick({ ...card, image_url: p.image_url || data.image_url, image_large: p.image_large || null,
        back_image: p.image_url ? p.back_image || null : base.back_image, set: p.set,
        prices: Object.keys(p.prices || {}).length ? (p.prices as any) : data.prices || {},
        print: { id: p.id, set: p.set, set_name: p.set_name, number: p.number } });
    }
    onClose();
  }

  return (
    <dialog ref={ref} className="printdlg" onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Издание: {card.name_ru || card.name}</h3>
        <button type="button" onClick={onClose} aria-label="Закрыть">✕</button>
      </div>
      {err ? <p className="loss small">{err}</p> : !data ? <p className="muted">Загружаем издания…</p> : (
        <>
          <div className="row" style={{ marginTop: 8 }}>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Сет: код или название"
              aria-label="Фильтр изданий" style={{ flex: 1, minWidth: 160 }} />
            <button type="button" className={!card.print ? "on" : ""} onClick={() => pick(null)}>По умолчанию</button>
            <span className="muted small">{prints.length} изд.</span>
          </div>
          {shown.length ? (
            <ul className="printgrid">
              {shown.map((p) => (
                <li key={p.id}>
                  <button type="button" className={card.print?.id === p.id ? "on" : ""} onClick={() => pick(p)}
                    title={`${p.set_name || p.set}${p.number ? ` №${p.number}` : ""}`}>
                    {p.image_url
                      ? <img src={viaSite(p.image_url.replace("/normal/", "/small/")) || ""} alt="" loading="lazy" decoding="async" />
                      : <span className="noimg small">{p.set.toUpperCase()}</span>}
                    <span className="small"><b className="pset">{p.set.toUpperCase()}</b> {p.number ? `№${p.number}` : ""}
                      {p.promo ? " · промо" : ""}{p.finishes?.includes("etched") ? " · etched" : ""}</span>
                    <span className="muted small">{p.released_at?.slice(0, 4)}{p.prices?.usd != null ? ` · $${p.prices.usd}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="muted small">{prints.length ? "Ничего не найдено." : "Других изданий у карты в базе нет."}</p>}
        </>
      )}
    </dialog>
  );
}
