"use client";

import Link from "next/link";
import Mana from "@/components/Mana";
import { COMMANDER_FORMATS, Row, count, displayName, grouped } from "@/lib/decks";

export type Ops = {
  qty: (key: string, delta: number) => void;
  move: (key: string, section: Row["section"]) => void;
  remove: (key: string) => void;
  print?: (key: string) => void;          // открыть выбор издания
};

function issue(r: Row, format: string, identity: Set<string> | null): string | null {
  const c = r.card;
  if (!c) return "нет в базе";
  if (format !== "casual") {
    const st = c.legalities?.[format];
    if (st === "banned") return "запрещена";
    if (st === "not_legal") return "не легальна";
  }
  if (identity && r.section === "main" && (c.color_identity || []).some((x) => !identity.has(x))) return "вне цветов";
  return null;
}

/** Список колоды по типам, как на Moxfield. ops - режим редактора (кнопки ±, перенос, удаление). */
export default function DeckList({ rows, format, lang, ops, onHover }: {
  rows: Row[]; format: string; lang: "ru" | "en"; ops?: Ops; onHover?: (r: Row) => void;
}) {
  const isCmd = COMMANDER_FORMATS.has(format);
  const commanders = rows.filter((r) => r.section === "commander" && r.card);
  const identity = isCmd && commanders.length ? new Set(commanders.flatMap((r) => r.card?.color_identity || [])) : null;
  const groups = grouped(rows);
  if (!groups.length) return <p className="muted">Колода пуста. Найдите карты в поиске выше и добавьте их.</p>;
  return (
    <div className="decklist">
      {groups.map(([g, label, rs]) => (
        <section key={g} className="deckgroup">
          <h3>{label} <span className="muted small num">{count(rs)}</span></h3>
          <ul>
            {rs.map((r) => {
              const bad = issue(r, format, identity);
              return (
                <li key={r.key} onMouseEnter={() => onHover?.(r)} onFocus={() => onHover?.(r)} className={bad ? "bad" : ""}>
                  {ops ? (
                    <span className="qtyctl">
                      <button type="button" aria-label="Убрать одну" onClick={() => ops.qty(r.key, -1)}>−</button>
                      <span className="num">{r.qty}</span>
                      <button type="button" aria-label="Добавить одну" onClick={() => ops.qty(r.key, 1)}>+</button>
                    </span>
                  ) : <span className="num qty">{r.qty}</span>}
                  <span className="cname">
                    {r.card && !ops ? <Link href={`/cards/${r.card.id}`}>{displayName(r, lang)}</Link>
                      : <button type="button" className="linkish" onClick={() => onHover?.(r)}>{displayName(r, lang)}</button>}
                    {r.card?.print ? <span className="muted small pset" title={`${r.card.print.set_name || ""}${r.card.print.number ? ` №${r.card.print.number}` : ""}`}> {r.card.print.set.toUpperCase()}</span> : null}
                    {r.card?.is_game_changer && isCmd ? <span className="gold small" title="Game Changer"> GC</span> : null}
                    {bad ? <span className="loss small"> · {bad}</span> : null}
                  </span>
                  <span className="cost"><Mana text={r.card?.mana_cost?.split(" // ")[0]} size={14} /></span>
                  {ops ? (
                    <select className="rowmenu" value="" aria-label={`Действия: ${r.name}`} onChange={(e) => {
                      const v = e.target.value;
                      if (v === "remove") ops.remove(r.key);
                      else if (v === "print") ops.print?.(r.key);
                      else if (v) ops.move(r.key, v as Row["section"]);
                    }}>
                      <option value="">⋯</option>
                      {r.card && ops.print ? <option value="print">Выбрать издание…</option> : null}
                      {r.section !== "main" ? <option value="main">В основную колоду</option> : null}
                      {r.section !== "side" ? <option value="side">В сайдборд</option> : null}
                      {isCmd && r.section !== "commander" ? <option value="commander">Сделать командиром</option> : null}
                      <option value="remove">Удалить</option>
                    </select>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
