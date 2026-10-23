"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import Guard from "@/components/Guard";
import { api, getToken } from "@/lib/api";
import { dateOnly } from "@/lib/format";

export default function PublisherPage() {
  return <Guard><Cabinet /></Guard>;
}

type Tab = "overview" | "clubs" | "tournaments" | "meta" | "decklists";
const TABS: [Tab, string][] = [["overview", "Обзор"], ["clubs", "Клубы"], ["tournaments", "Турниры"], ["meta", "Мета"], ["decklists", "Деклисты"]];
const FORMAT: Record<string, string> = { swiss: "Швейцарка", edh: "EDH", single_elim: "Олимпийка" };

async function download(path: string, name: string) {
  const r = await fetch("/api" + path, { headers: { Authorization: `Bearer ${getToken() || ""}` } });
  if (!r.ok) throw new Error("Не удалось выгрузить");
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function Cabinet() {
  const [me, setMe] = useState<any>(undefined);
  const [game, setGame] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  useEffect(() => {
    api<any>("/publisher/me").then((x) => { setMe(x); setGame(x.games[0]?.code || ""); }).catch(() => setMe(null));
  }, []);
  if (me === undefined) return <p className="muted">Загружаем…</p>;
  if (!me) return <p>Это кабинет издателя игры. Доступ выдаёт администратор сайта.</p>;
  const qs = new URLSearchParams();
  if (from) qs.set("from", from);
  if (to) qs.set("to", to);
  const q = qs.toString() ? `?${qs}` : "";
  return (
    <>
      <h1>Кабинет издателя</h1>
      <p className="lead">{me.name}: статистика по всем клубам платформы. Итоги турниров и мета — без согласия игроков,
        деклисты с ником — только тех, кто разрешил передавать их издателю.</p>
      <div className="row">
        {me.games.length > 1 ? (
          <span className="seg" role="group" aria-label="Игра">
            {me.games.map((g: any) => <button key={g.code} className={game === g.code ? "on" : ""} onClick={() => setGame(g.code)}>{g.title}</button>)}
          </span>
        ) : <b>{me.games[0]?.title}</b>}
        <label className="row" style={{ gap: 6, margin: 0 }}><span className="small muted">с</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={{ width: "auto" }} /></label>
        <label className="row" style={{ gap: 6, margin: 0 }}><span className="small muted">по</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} style={{ width: "auto" }} /></label>
        {from || to ? <button type="button" className="link-btn" onClick={() => { setFrom(""); setTo(""); }}>весь период</button> : null}
      </div>
      <div className="tabs section" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {game ? <Section key={`${game}${tab}${q}`} game={game} tab={tab} q={q} /> : null}
    </>
  );
}

function Export({ game, kind, q, label }: { game: string; kind: string; q: string; label: string }) {
  const [err, setErr] = useState("");
  return (
    <span>
      <button type="button" onClick={() => download(`/publisher/${game}/export/${kind}.csv${q}`, `${game}-${kind}.csv`).catch((e) => setErr(e.message))}>
        {label}
      </button>
      {err ? <span className="err small"> {err}</span> : null}
    </span>
  );
}

function Section({ game, tab, q }: { game: string; tab: Tab; q: string }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const path = tab === "meta" ? `/publisher/${game}/meta` : `/publisher/${game}/${tab}${q}`;
    api(path).then(setD).catch((e) => setErr(e.message));
  }, [game, tab, q]);
  if (err) return <p className="err">{err}</p>;
  if (!d) return <p className="muted">Загружаем…</p>;

  if (tab === "overview") {
    return (
      <>
        <div className="row stat-tiles">
          {[["Турниров", d.tournaments], ["Клубов", d.clubs], ["Игроков", d.players], ["Участий", d.participations],
            ["В среднем на турнире", d.avg_participants]].map(([l, v]) => (
            <div key={l as string} className="panel" style={{ minWidth: 140 }}><b className="num">{v}</b><span className="muted small">{l}</span></div>
          ))}
        </div>
        {d.by_month.length ? (
          <div className="table-wrap section">
            <table>
              <thead><tr><th>Месяц</th><th className="num">Турниров</th><th className="num">Участий</th></tr></thead>
              <tbody>{d.by_month.map((m: any) => <tr key={m.month}><td>{m.month}</td><td className="num">{m.tournaments}</td><td className="num">{m.participants}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <p className="muted section">Завершённых турниров за период нет.</p>}
        {Object.keys(d.formats).length ? (
          <p className="small muted">Форматы: {Object.entries(d.formats).map(([f, n]) => `${FORMAT[f] || f} — ${n}`).join(", ")}</p>
        ) : null}
      </>
    );
  }
  if (tab === "clubs") {
    return (
      <>
        <Export game={game} kind="clubs" q={q} label="Скачать CSV" />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Клуб</th><th>Город</th><th className="num">Турниров</th><th className="num">Игроков</th><th className="num">Участий</th><th>Последний</th></tr></thead>
            <tbody>{d.map((c: any) => (
              <tr key={c.id}><td><Link href={c.url || "#"}>{c.name}</Link></td><td>{c.city}</td><td className="num">{c.tournaments}</td>
                <td className="num">{c.players}</td><td className="num">{c.participations}</td><td>{c.last ? dateOnly(c.last) : ""}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </>
    );
  }
  if (tab === "tournaments") {
    return (
      <>
        <Export game={game} kind="tournaments" q={q} label="Скачать CSV" />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Дата</th><th>Клуб</th><th>Турнир</th><th>Формат</th><th className="num">Игроков</th><th>Победитель</th></tr></thead>
            <tbody>{d.map((t: any) => (
              <tr key={t.id}><td>{dateOnly(t.date)}</td><td>{t.club}</td><td><Link href={`/tournaments/${t.id}`}>{t.name}</Link></td>
                <td>{FORMAT[t.format] || t.format}</td><td className="num">{t.participants}</td><td>{t.winner || "—"}</td></tr>
            ))}</tbody>
          </table>
        </div>
        {!d.length ? <p className="muted">Завершённых турниров за период нет.</p> : null}
      </>
    );
  }
  if (tab === "meta") {
    const cards = d.cards?.cards || [];
    return (
      <>
        <p className="muted small">Колод с завершённых турниров за 90 дней: {d.tournament_decks}; колод «в мете» из пулов игроков: {d.players_pool?.decks ?? 0}. Без имён.</p>
        {d.commanders.length ? (
          <>
            <h2>Командиры</h2>
            <div className="table-wrap"><table>
              <thead><tr><th>Командир</th><th className="num">Колод</th><th className="num">Доля</th></tr></thead>
              <tbody>{d.commanders.map((c: any) => <tr key={c.commander}><td>{c.commander}</td><td className="num">{c.decks}</td><td className="num">{Math.round((c.pick_rate || 0) * 100)}%</td></tr>)}</tbody>
            </table></div>
          </>
        ) : null}
        {d.berserk ? <BerserkMeta bk={d.berserk} /> : null}
        <h2>Карты в турнирных колодах</h2>
        {cards.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Карта</th><th className="num">Колод</th><th className="num">Доля</th></tr></thead>
            <tbody>{cards.map((c: any) => <tr key={c.card}><td>{c.card}</td><td className="num">{c.decks}</td><td className="num">{c.usage_pct}%</td></tr>)}</tbody>
          </table></div>
        ) : <p className="muted">Пока мало данных: деклисты подаются при записи на турнир.</p>}
      </>
    );
  }
  return (
    <>
      <div className="row"><Export game={game} kind="decklists" q={q} label="Скачать CSV" />
        <span className="muted small">Игроков, разрешивших передачу: {d.consented_players}</span></div>
      {d.items.length ? (
        <div className="stack section">
          {d.items.map((x: any, i: number) => (
            <details key={i} className="panel">
              <summary><b>{x.player}</b>{x.player_no ? ` №${x.player_no}` : ""} · {x.place ? `${x.place}-е место` : "место —"} · {x.tournament}
                <span className="muted small"> · {x.club}, {dateOnly(x.date)}</span></summary>
              <ul className="small" style={{ columns: "2 220px", margin: "10px 0 0" }}>
                {x.cards.map((c: any, j: number) => <li key={j}>{c.qty} {c.name}{c.section === "side" ? " (сайд)" : c.section === "commander" ? " (командир)" : ""}</li>)}
              </ul>
            </details>
          ))}
        </div>
      ) : <p className="muted section">Деклистов от игроков с согласием за период нет.</p>}
    </>
  );
}

const pct = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

/** Мета «Берсерка»: связки стихий и архетипы с результатами, доли стихий, профиль колод.
 *  Две выборки: колоды с завершённых турниров клубов и колоды, которые игроки отметили «в мете». */
function BerserkMeta({ bk }: { bk: any }) {
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
        <p className="muted">{results ? "Колод с завершённых турниров «Берсерка» за 90 дней пока нет." : "Игроки ещё не отмечали колоды «Учитывать в мете»."}</p>
      ) : (
        <>
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
