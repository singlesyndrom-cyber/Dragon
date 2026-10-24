"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import Mana from "@/components/Mana";
import { api } from "@/lib/api";
import { viaSite } from "@/lib/img";
import { useAuth } from "@/lib/auth";
import { formatTitle, formatsFor } from "@/lib/decks";
import { dateOnly, GAME_LIST } from "@/lib/format";

export default function DecksPage() {
  return <Suspense fallback={<h1>Колоды</h1>}><Catalogue /></Suspense>;
}

function Catalogue() {
  const p = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const { me } = useAuth();
  const game = ["berserk", "response"].includes(p.get("game") || "") ? p.get("game")! : "mtg";
  const format = p.get("format") || "";
  const q = p.get("q") || "";
  const page = Math.max(1, Number(p.get("page")) || 1);
  const [text, setText] = useState(q);
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    const qs = new URLSearchParams({ page: String(page), game });
    if (format) qs.set("format", format);
    if (q) qs.set("q", q);
    api(`/decks/public?${qs}`).then(setData).catch(() => setData({ items: [], total: 0, per_page: 30 }));
  }, [format, q, page, game]);

  function go(ch: Record<string, string>) {
    const n = new URLSearchParams(p.toString());
    for (const [k, v] of Object.entries(ch)) v ? n.set(k, v) : n.delete(k);
    if (!("page" in ch)) n.delete("page");
    router.push(`${path}?${n}`);
  }
  const pages = data ? Math.ceil(data.total / data.per_page) : 0;
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Колоды</h1>
        {me ? <span className="row" style={{ gap: 8 }}><Link href="/me#decks" className="btn">Мои колоды</Link>
          <Link href={`/decks/new?game=${game}`} className="btn primary">Новая колода</Link></span> : null}
      </div>
      <p className="lead">Публичные колоды игроков. Откройте любую, чтобы посмотреть статистику, разыграть тестовую руку или скопировать себе.</p>
      <div className="tabs section" role="tablist" aria-label="Игра">
        {GAME_LIST.map(([g, l]) => (
          <button key={g} type="button" role="tab" aria-selected={game === g} className={game === g ? "on" : ""}
            onClick={() => go({ game: g === "mtg" ? "" : g, format: "" })}>{l}</button>
        ))}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); go({ q: text.trim() }); }}>
        <input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder={game === "berserk" ? "Название колоды" : game === "response" ? "Название колоды или герой" : "Название колоды или командир"}
          aria-label="Поиск колод" style={{ flex: 1, minWidth: 200 }} />
        <select value={format} onChange={(e) => go({ format: e.target.value })} aria-label="Формат" style={{ width: "auto" }}>
          <option value="">Все форматы</option>
          {formatsFor(game).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button type="submit">Найти</button>
      </form>
      {!data ? <p className="muted section">Загружаем…</p> : !data.items.length ? (
        <p className="muted section">Публичных колод {format || q ? "по этому запросу " : ""}пока нет.{me ? " Сделайте свою колоду публичной — она появится здесь." : ""}</p>
      ) : (
        <div className="deckcards section">
          {data.items.map((d: any) => {
            const cmd = d.commanders[0];
            const ci: string[] = Array.from(new Set(d.commanders.flatMap((c: any) => c.color_identity)));
            return (
              <Link key={d.id} href={`/decks/${d.id}`} className="deckcard">
                {cmd?.image_url ? <img src={viaSite(cmd.image_url) || ""} alt="" loading="lazy" /> : <span className="noimg">{formatTitle(d.format)}</span>}
                <span className="cap">
                  <b>{d.name}</b>
                  <span className="muted small">{formatTitle(d.format)} · {d.author}</span>
                  {d.commanders.length ? <span className="small">{d.commanders.map((c: any) => c.name).join(" + ")}</span> : null}
                  <span className="row small muted" style={{ justifyContent: "space-between", gap: 6 }}>
                    <span>{ci.length ? <Mana text={["W", "U", "B", "R", "G"].filter((c) => ci.includes(c)).map((c) => `{${c}}`).join("")} size={14} /> : null}
                      {" "}{d.cards} карт{d.usd ? ` · $${Math.round(d.usd)}` : ""}</span>
                    <span>{dateOnly(d.updated_at)}</span>
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      )}
      {pages > 1 ? (
        <nav className="row pager" aria-label="Страницы">
          <button disabled={page <= 1} onClick={() => go({ page: String(page - 1) })}>← Назад</button>
          <span className="muted small">Страница {page} из {pages}</span>
          <button disabled={page >= pages} onClick={() => go({ page: String(page + 1) })}>Дальше →</button>
        </nav>
      ) : null}
    </>
  );
}
