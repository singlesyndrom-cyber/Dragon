"use client";

import { useState } from "react";

const pct = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

/** Мета «Берсерка»: связки стихий и архетипы с результатами, доли стихий, профиль колод.
 *  Две выборки: колоды с завершённых турниров клубов и колоды, которые игроки отметили «в мете». */
export default function BerserkMeta({ bk }: { bk: any }) {
  const [src, setSrc] = useState<"tournaments" | "pool">(bk.tournaments.decks || !bk.pool.decks ? "tournaments" : "pool");
  const m = bk[src];
  const results = src === "tournaments";
  return (
    <section className="section">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Мета «Берсерка»</h2>
        <span className="seg" role="group" aria-label="Выборка">
          <button type="button" className={src === "tournaments" ? "on" : ""} onClick={() => setSrc("tournaments")}>
            Турниры клубов · {bk.tournaments.decks}</button>
          <button type="button" className={src === "pool" ? "on" : ""} onClick={() => setSrc("pool")}>
            Колоды «в мете» · {bk.pool.decks}</button>
        </span>
      </div>
      {!m.decks ? (
        <p className="muted">{results ? "Колод с завершённых турниров «Берсерка» за 90 дней пока нет." : "Игроки ещё не отмечали колоды «Учитывать в мете»."}
          {m.skipped ? ` Колод без карт из базы (список не распознан): ${m.skipped} — они не учитываются.` : ""}</p>
      ) : (
        <>
          {m.skipped ? <p className="muted small">Ещё {m.skipped} колод без карт из базы не учтено: их список не распознан.</p> : null}
          <div className="row stat-tiles section">
            <div><b className="num">{m.profile.size}</b><span className="muted small">карт в колоде</span></div>
            <div><b className="num">{m.profile.avg_cost.toFixed(1)}</b><span className="muted small">средняя стоимость</span></div>
            <div><b className="num">{pct(m.profile.elite_share)}</b><span className="muted small">элитных карт</span></div>
            <div><b className="num">{pct(m.profile.flyer_share)}</b><span className="muted small">летающих</span></div>
            <div><b className="num">{m.profile.colors}</b><span className="muted small">стихий в колоде</span></div>
          </div>

          <h3>Стихии <span className="muted small">в какой доле колод встречается стихия</span></h3>
          <div className="pips">
            {m.elements.map((e: any) => (
              <div key={e.element} className="pip-row" style={{ gridTemplateColumns: "92px 1fr auto" }} title={`${e.element}: ${e.decks} колод`}>
                <span className="small">{e.element}</span>
                <div className="pip-track"><div className="pip-bar" style={{ width: `${e.share * 100}%` }} /></div>
                <span className="small num">{e.decks} · {pct(e.share)}</span>
              </div>
            ))}
          </div>

          <MetaTable title="Связки стихий" hint="по картам колоды; нейтральные карты стихией не считаются" rows={m.combos} results={results} />
          <MetaTable title="Архетипы" hint="по названию колоды, без учёта регистра" rows={m.archetypes} results={results} />
          {results ? <p className="muted small">Винрейт — по матчам швейцарки; ожидаемый 50%, «±» — отклонение от него. Серым — меньше 3 партий, выводы делать рано.</p> : null}
        </>
      )}
    </section>
  );
}

function MetaTable({ title, hint, rows, results }: { title: string; hint: string; rows: any[]; results: boolean }) {
  if (!rows.length) return null;
  return (
    <>
      <h3>{title} <span className="muted small">{hint}</span></h3>
      <div className="table-wrap"><table>
        <thead><tr><th>{title === "Архетипы" ? "Архетип" : "Стихии"}</th><th className="num">Колод</th><th className="num">Доля</th>
          {results ? <><th className="num">Партий</th><th className="num">П-Н-П</th><th className="num">Винрейт</th><th className="num">±</th></> : null}</tr></thead>
        <tbody>{rows.slice(0, 30).map((r) => (
          <tr key={r.key} className={results && !r.reliable ? "muted" : ""}>
            <td>{r.key}</td><td className="num">{r.decks}</td><td className="num">{pct(r.pick_rate)}</td>
            {results ? <><td className="num">{r.games}</td><td className="num">{r.wins}-{r.draws}-{r.losses}</td>
              <td className="num">{pct(r.win_rate)}</td>
              <td className={`num ${r.edge > 0 ? "win" : r.edge < 0 ? "loss" : ""}`}>{r.edge == null ? "—" : `${r.edge > 0 ? "+" : ""}${Math.round(r.edge * 100)}`}</td></> : null}
          </tr>
        ))}</tbody>
      </table></div>
    </>
  );
}
