"use client";

import { Fragment } from "react";
import Mana from "@/components/Mana";
import { GROUPS, Row, count, playing, stats } from "@/lib/decks";

/** Статистика колоды: кривая маны, цвета (символы маны в стоимостях), типы, цена.
 *  Один цвет столбцов: значение подписано числом, цвет не несёт смысла сам по себе. */
export default function DeckStats({ rows }: { rows: Row[] }) {
  const s = stats(rows);
  const maxCurve = Math.max(1, ...s.curve);
  const pipTotal = Object.values(s.pips).reduce((a, b) => a + b, 0);
  const maxPip = Math.max(1, ...Object.values(s.pips));
  const types = GROUPS.filter(([g]) => s.types[g]);
  return (
    <div className="deckstats">
      <div className="row stat-tiles">
        <div><b className="num">{count(playing(rows))}</b><span className="muted small">карт</span></div>
        <div><b className="num">{s.avg.toFixed(2)}</b><span className="muted small">средняя стоимость</span></div>
        <div><b className="num">{s.lands}</b><span className="muted small">земель</span></div>
        {s.usd ? <div><b className="num">${s.usd.toFixed(0)}</b><span className="muted small">{s.eur ? `€${s.eur.toFixed(0)}` : "цена"}</span></div> : null}
      </div>

      <h3>Кривая маны</h3>
      <div className="curve" role="img" aria-label={`Кривая маны: ${s.curve.map((n, i) => `${i === 7 ? "7+" : i} — ${n}`).join(", ")}`}>
        {s.curve.map((n, i) => (
          <div key={i} className="curve-col" title={`Стоимость ${i === 7 ? "7+" : i}: ${n} карт`}>
            <span className="small num">{n || ""}</span>
            <div className="curve-bar" style={{ height: `${(n / maxCurve) * 100}%` }} />
            <span className="muted small">{i === 7 ? "7+" : i}</span>
          </div>
        ))}
      </div>
      <p className="muted small" style={{ margin: "4px 0 0" }}>Без земель.</p>

      {pipTotal ? (
        <>
          <h3>Цвета в стоимостях</h3>
          <div className="pips">
            {Object.entries(s.pips).filter(([, n]) => n).map(([c, n]) => (
              <div key={c} className="pip-row" title={`{${c}}: ${n} символов, ${Math.round((n / pipTotal) * 100)}%`}>
                <Mana text={`{${c}}`} size={18} />
                <div className="pip-track"><div className="pip-bar" style={{ width: `${(n / maxPip) * 100}%` }} /></div>
                <span className="small num">{n} · {Math.round((n / pipTotal) * 100)}%</span>
              </div>
            ))}
          </div>
        </>
      ) : null}

      <h3>Типы</h3>
      <dl className="facts small">
        {types.map(([g, label]) => <Fragment key={g}><dt>{label}</dt><dd className="num">{s.types[g]}</dd></Fragment>)}
      </dl>
    </div>
  );
}
