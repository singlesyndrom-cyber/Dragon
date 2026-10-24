"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";
import DeckList from "@/components/deck/DeckList";
import FlipCard from "@/components/FlipCard";
import DeckStats from "@/components/deck/DeckStats";
import ExportBox from "@/components/deck/ExportBox";
import Problems from "@/components/deck/Problems";
import SquadBuilder from "@/components/deck/SquadBuilder";
import TestHand from "@/components/deck/TestHand";
import { useLang } from "@/components/deck/useLang";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Row, VISIBILITY, formatTitle, fromApi } from "@/lib/decks";
import { dateOnly } from "@/lib/format";
import BracketInfo from "@/components/BracketInfo";

export default function DeckPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Suspense fallback={<p className="muted">Загружаем…</p>}><Deck id={id} /></Suspense>;
}

function Deck({ id }: { id: string }) {
  const key = useSearchParams().get("key");
  const router = useRouter();
  const { me, ready } = useAuth();
  const [d, setD] = useState<any>(undefined);
  const [rows, setRows] = useState<Row[]>([]);
  const [preview, setPreview] = useState<Row | null>(null);
  const [tab, setTab] = useState<"list" | "stats" | "hand" | "export">("list");
  const [lang, setLang] = useLang();
  const [linkCopied, setLinkCopied] = useState(false);
  const { busy, error, run } = useAction();

  useEffect(() => {
    if (!ready) return;
    api(`/decks/${id}${key ? `?key=${encodeURIComponent(key)}` : ""}`).then((x: any) => {
      setD(x);
      const rs = fromApi(x.cards);
      setRows(rs);
      setPreview(rs.find((r) => r.section === "commander" && r.card) || rs.find((r) => r.card) || null);
    }).catch(() => setD(null));
  }, [id, key, ready, me?.id]);

  if (d === undefined) return <p className="muted">Загружаем…</p>;
  if (!d) {
    return <p>Колода не найдена или скрыта владельцем. Личную колоду видят только владелец и организаторы турнира, на который она подана.</p>;
  }

  async function share() {
    const url = `${location.origin}/decks/${d.id}${d.visibility === "link" && d.share_key ? `?key=${d.share_key}` : ""}`;
    try { await navigator.clipboard.writeText(url); setLinkCopied(true); setTimeout(() => setLinkCopied(false), 2000); } catch {}
  }
  const img = preview?.card?.image_large || preview?.card?.image_url;
  return (
    <>
      <p className="muted small"><Link href="/decks">← Колоды</Link></p>
      <h1 style={{ marginBottom: 4 }}>{d.name}</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        {d.game === "mtg" ? formatTitle(d.format) : `Берсерк · ${formatTitle(d.format)}`}
        {d.owner ? <> · {d.owner.nickname}</> : null}
        {d.updated_at ? <> · обновлена {dateOnly(d.updated_at)}</> : null}
        {d.editable ? <> · {VISIBILITY.find(([k]) => k === d.visibility)?.[1]}</> : null}
      </p>
      <div className="row">
        {d.editable ? <Link href={`/decks/${d.id}/edit`} className="btn primary">Редактировать</Link> : null}
        {d.visibility !== "private" ? <button type="button" onClick={share}>{linkCopied ? "Ссылка скопирована" : "Скопировать ссылку"}</button> : null}
        {me && !d.editable ? (
          <button type="button" disabled={busy} onClick={() => run(async () => {
            const r = await api<any>(`/decks/${d.id}/copy${key ? `?key=${encodeURIComponent(key)}` : ""}`, { method: "POST" });
            router.push(`/decks/${r.id}/edit`);
          })}>Скопировать себе</button>
        ) : null}
        <span className="seg" role="group" aria-label="Язык названий" style={{ marginLeft: "auto" }}>
          <button type="button" className={lang === "ru" ? "on" : ""} onClick={() => setLang("ru")}>RU</button>
          <button type="button" className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>EN</button>
        </span>
      </div>
      <Status error={error} />
      {d.locked ? <p className="hint">Колода подана на начавшийся турнир — редактирование закрыто до его окончания.</p> : null}
      <Problems problems={d.problems} />
      {d.bracket ? <BracketInfo a={d.bracket} /> : null}

      <div className="tabs section" role="tablist">
        {([["list", "Список"], ["stats", "Статистика"], ["hand", d.game === "berserk" ? "Набор отряда" : "Тестовая рука"], ["export", "Экспорт"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === "list" ? (
        <div className="deckview">
          <DeckList rows={rows} format={d.format} lang={lang} onHover={setPreview} game={d.game} />
          <aside className="deckpreview"><FlipCard front={img} back={preview?.card?.back_image} alt={preview?.name || ""} /></aside>
        </div>
      ) : tab === "stats" ? <DeckStats rows={rows} />
        : tab === "hand" ? (d.game === "berserk" ? <SquadBuilder rows={rows} lang={lang} /> : <TestHand rows={d.game === "response" ? rows.filter((r) => r.section === "main") : rows} lang={lang} />)
        : <ExportBox rows={rows} name={d.name} />}
    </>
  );
}
