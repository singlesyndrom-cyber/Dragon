"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import FlipCard from "@/components/FlipCard";
import Mana from "@/components/Mana";
import WotcNotice from "@/components/WotcNotice";
import { api } from "@/lib/api";
import { GAMES, ORDER_LABELS, RARITY_RU, gameInfo, searchHref } from "@/lib/cards";
import { dateOnly } from "@/lib/format";

type View = "grid" | "list" | "text";
const VIEWS: [View, string][] = [["grid", "Картинки"], ["list", "Список"], ["text", "Текст"]];
const PER_PAGE = 60;

function loadView(): View {
  try {
    const v = localStorage.getItem("cards-view");
    if (v === "grid" || v === "list" || v === "text") return v;
  } catch {}
  return "grid";
}

function SearchBox({ q, game, big }: { q: string; game: string; big?: boolean }) {
  const router = useRouter();
  const [value, setValue] = useState(q);
  useEffect(() => setValue(q), [q]);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (value.trim()) router.push(searchHref(value.trim(), game));
  }
  return (
    <form onSubmit={submit} className={big ? "cardsearch big" : "cardsearch"} role="search">
      <input type="search" value={value} onChange={(e) => setValue(e.target.value)} autoFocus={big}
        placeholder={game === "mtg" ? "Название по-русски или по-английски, или запрос: t:dragon c:r mv<=5" : "Название или запрос"}
        aria-label="Поиск карт" />
      <button type="submit">Найти</button>
    </form>
  );
}

function GameTabs({ game, stats, q }: { game: string; stats: any; q: string }) {
  const router = useRouter();
  const codes = Array.from(new Set([...GAMES.map((g) => g.code), ...Object.keys(stats?.games || {})]))
    .filter((c) => c === "mtg" || stats?.games?.[c]);
  return (
    <div className="tabs" role="tablist" aria-label="Игра">
      {codes.map((c) => {
        const n = stats?.games?.[c]?.cards;
        return (
          <button key={c} role="tab" aria-selected={c === game} className={c === game ? "on" : ""}
            onClick={() => router.push(q ? searchHref(q, c) : `/cards?game=${c}`)}>
            {gameInfo(c).title}{n ? <span className="muted small"> · {n.toLocaleString("ru-RU")}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

function Landing({ game, stats }: { game: string; stats: any }) {
  const info = gameInfo(game);
  const s = stats?.games?.[game];
  return (
    <>
      <SearchBox q="" game={game} big />
      <p className="muted small">
        <Link href={`/cards/advanced?game=${game}`}>Расширенный поиск</Link> · <Link href="/cards/syntax">Синтаксис запросов</Link>
        {" · "}<Link href={searchHref("*", game)}>Все карты {info.short}</Link>
      </p>
      {s ? (
        <p className="muted small">
          {s.cards.toLocaleString("ru-RU")} карт{game === "mtg" ? `, ${s.russian.toLocaleString("ru-RU")} с русским названием` : ""}
          {game === "mtg" && stats.scryfall_updated ? `. Обновлено ${dateOnly(stats.scryfall_updated)}` : ""}.
        </p>
      ) : game === "mtg" ? (
        <p className="muted small">База карт ещё загружается: первая загрузка из Scryfall занимает несколько минут.</p>
      ) : null}
      {game === "mtg" ? (
        <section className="section">
          <h2>По цвету</h2>
          <div className="row">
            {["W", "U", "B", "R", "G", "C"].map((c) => (
              <Link key={c} href={searchHref(c === "C" ? "c:c" : `c=${c.toLowerCase()}`, game)} className="manalink"
                aria-label={`Карты цвета ${c}`}><Mana text={`{${c}}`} size={30} /></Link>
            ))}
            <Link href={searchHref("c:m", game)} className="small">многоцветные</Link>
          </div>
        </section>
      ) : null}
      {info.examples.length ? (
        <section className="section">
          <h2>Попробуйте</h2>
          <ul className="examples">
            {info.examples.map(([q, label]) => (
              <li key={q}><Link href={searchHref(q, game)}><code>{q}</code></Link> <span className="muted">— {label}</span></li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function Pager({ page, pages, go }: { page: number; pages: number; go: (p: number) => void }) {
  if (pages <= 1) return null;
  return (
    <nav className="row pager" aria-label="Страницы">
      <button disabled={page <= 1} onClick={() => go(page - 1)}>← Назад</button>
      <span className="muted small">Страница {page} из {pages}</span>
      <button disabled={page >= pages} onClick={() => go(page + 1)}>Дальше →</button>
    </nav>
  );
}

function Pt({ c }: { c: any }) {
  if (c.power != null) return <>{c.power}/{c.toughness}</>;
  if (c.loyalty != null) return <>верн. {c.loyalty}</>;
  return null;
}

function Results({ q, game, order, dir, page }: { q: string; game: string; order: string; dir: string; page: number }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [view, setView] = useState<View>("grid");
  useEffect(() => setView(loadView()), []);

  useEffect(() => {
    setErr("");
    const qs = new URLSearchParams({ q, game, page: String(page), per_page: String(PER_PAGE) });
    if (order) qs.set("order", order);
    if (dir) qs.set("dir", dir);
    api(`/cards/search?${qs}`).then(setData).catch((e) => setErr(e.message));
  }, [q, game, order, dir, page]);

  function set(changes: Record<string, string>) {
    const p = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) v ? p.set(k, v) : p.delete(k);
    if (!("page" in changes)) p.delete("page");
    router.push(`${path}?${p}`);
  }
  function chooseView(v: View) {
    setView(v);
    try { localStorage.setItem("cards-view", v); } catch {}
  }

  const pages = data ? Math.ceil(data.total / PER_PAGE) : 0;
  return (
    <>
      <SearchBox q={q} game={game} />
      <div className="row results-bar">
        <span className="muted small">
          {data ? <>{data.total.toLocaleString("ru-RU")} карт{data.total > PER_PAGE ? `, ${(page - 1) * PER_PAGE + 1}–${Math.min(page * PER_PAGE, data.total)}` : ""}</> : "Ищем…"}
          {" · "}<Link href={`/cards/advanced?game=${game}`}>расширенный поиск</Link> · <Link href="/cards/syntax">синтаксис</Link>
        </span>
        <span className="row" style={{ marginLeft: "auto", gap: 8 }}>
          <select value={data?.order || order || "name"} onChange={(e) => set({ order: e.target.value })} aria-label="Сортировка">
            {ORDER_LABELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <button onClick={() => set({ dir: (data?.dir || dir) === "desc" ? "asc" : "desc" })}
            aria-label="Направление сортировки" title="Направление сортировки">{(data?.dir || dir) === "desc" ? "↓" : "↑"}</button>
          <span className="seg" role="group" aria-label="Вид">
            {VIEWS.map(([v, l]) => <button key={v} className={view === v ? "on" : ""} onClick={() => chooseView(v)}>{l}</button>)}
          </span>
        </span>
      </div>
      {data?.warnings?.length ? <ul className="hint warnings">{data.warnings.map((w: string) => <li key={w}>{w}</li>)}</ul> : null}
      {err ? <p className="err">{err}</p> : null}
      {data && !data.items.length ? (
        <p className="muted section">Ничего не найдено. Проверьте написание, попробуйте название на другом языке или загляните в <Link href="/cards/syntax">синтаксис</Link>.</p>
      ) : null}
      {data?.items.length ? (
        view === "grid" ? (
          <div className="grid section">
            {data.items.map((c: any) => (
              <Link key={c.id} href={`/cards/${c.id}`} className="tile">
                {c.image_url ? <FlipCard front={c.image_url} back={c.back_image} alt={c.name} lazy /> : <span className="noimg">{c.name_ru || c.name}</span>}
                <span className="cap">
                  <b>{c.name_ru || c.name}</b>
                  {c.name_ru ? <span className="muted small">{c.name}<br /></span> : null}
                  <span className="small"><Mana text={c.mana_cost} size={14} /></span>
                </span>
              </Link>
            ))}
          </div>
        ) : view === "list" ? (
          <div className="table-wrap section">
            <table className="cardlist">
              <thead><tr><th>Название</th><th>Стоимость</th><th>Тип</th><th>Сет</th><th>Редкость</th><th className="num">Цена</th></tr></thead>
              <tbody>
                {data.items.map((c: any) => (
                  <tr key={c.id}>
                    <td><Link href={`/cards/${c.id}`}>{c.name_ru || c.name}</Link>{c.name_ru ? <div className="muted small">{c.name}</div> : null}</td>
                    <td><Mana text={c.mana_cost} size={14} /></td>
                    <td className="small">{c.type_ru || c.type}</td>
                    <td className="small muted">{(c.set || "").toUpperCase()}</td>
                    <td className="small">{RARITY_RU[c.rarity] || c.rarity || ""}</td>
                    <td className="num small">{c.prices?.usd ? `$${c.prices.usd}` : c.prices?.eur ? `€${c.prices.eur}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="textcards section">
            {data.items.map((c: any) => (
              <article key={c.id} className="panel">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <Link href={`/cards/${c.id}`}><b>{c.name_ru || c.name}</b></Link>
                  <Mana text={c.mana_cost} size={15} />
                </div>
                {c.name_ru ? <div className="muted small">{c.name}</div> : null}
                <p className="muted small" style={{ margin: "6px 0" }}>{c.type_ru || c.type}</p>
                {(c.text_ru || c.text || "").split("\n").map((line: string, i: number) => (
                  <p key={i} className="small" style={{ margin: "0 0 0.4em" }}><Mana text={line} size={13} /></p>
                ))}
                <div className="row small muted" style={{ justifyContent: "space-between" }}>
                  <span>{(c.set || "").toUpperCase()} · {RARITY_RU[c.rarity] || c.rarity || ""}</span>
                  <span className="gold"><Pt c={c} /></span>
                </div>
              </article>
            ))}
          </div>
        )
      ) : null}
      <Pager page={page} pages={pages} go={(p) => { set({ page: String(p) }); window.scrollTo(0, 0); }} />
    </>
  );
}

function Cardfile() {
  const p = useSearchParams();
  const q = p.get("q") || "";
  const game = p.get("game") || "mtg";
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { api("/cards/stats").then(setStats).catch(() => {}); }, []);
  return (
    <>
      <h1>Картотека</h1>
      {!q ? <p className="lead">Поиск карт по названию, тексту, типу, цветам и форматам — на русском и английском.</p> : null}
      <GameTabs game={game} stats={stats} q={q} />
      {q ? (
        <Results q={q} game={game} order={p.get("order") || ""} dir={p.get("dir") || ""}
          page={Math.max(1, Number(p.get("page")) || 1)} />
      ) : <Landing game={game} stats={stats} />}
      {game === "mtg" ? <WotcNotice /> : null}
    </>
  );
}

export default function CardsPage() {
  return <Suspense fallback={<h1>Картотека</h1>}><Cardfile /></Suspense>;
}
