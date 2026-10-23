"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import { api } from "@/lib/api";

export default function NoticeImagesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Pool clubId={Number(id)} /></Guard>;
}

type Img = { id: number; purpose: string; game: string; preview: string; kind: string; card_name?: string;
  credit?: string; enabled: boolean; uses: number; width?: number; height?: number };

function Pool({ clubId }: { clubId: number }) {
  const base = `/clubs/${clubId}/notice-images`;
  const [data, setData] = useState<any>(undefined);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"announce" | "other">("announce");
  const load = () => api(base).then(setData).catch((e) => { setErr(e.message); setData(null); });
  useEffect(() => { load(); }, [clubId]);
  if (data === undefined) return <p className="muted">Загружаем…</p>;
  if (!data) return <p>{err || "Картинками оповещений управляют организаторы и судьи клуба."}</p>;
  const items: Img[] = data.items.filter((i: Img) => i.purpose === tab);
  const games: Record<string, string> = data.games;
  return (
    <>
      <p className="muted small"><Link href={`/manage/clubs/${clubId}`}>← Управление клубом</Link></p>
      <h1>Картинки оповещений</h1>
      <p className="lead">Картинка добавляется к анонсам и итогам в Telegram и беседах VK. Каждый раз берётся та, что
        дольше всех не использовалась; для турнира подходят картинки его игры и «любой игры».</p>
      <div className="tabs" role="tablist">
        {(Object.entries(data.purposes) as [string, string][]).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k as any)}>
            {l} <span className="muted small">{data.items.filter((i: Img) => i.purpose === k).length}</span>
          </button>
        ))}
      </div>
      <div className="split">
        <div>
          {items.length ? (
            <div className="imgpool">
              {items.map((i) => <ImageCard key={i.id} img={i} games={games} base={base} onChange={load} />)}
            </div>
          ) : <p className="muted">Картинок пока нет — оповещения уходят только текстом.</p>}
        </div>
        <aside className="stack">
          <Upload base={base} purpose={tab} games={games} onDone={load} />
          {tab === "announce" ? <CardArt base={base} games={games} onDone={load} /> : null}
          <p className="muted small">Арты карт Magic: The Gathering принадлежат Wizards of the Coast и указанным художникам;
            под анонсом с артом бот подписывает художника.</p>
        </aside>
      </div>
    </>
  );
}

function ImageCard({ img, games, base, onChange }: { img: Img; games: Record<string, string>; base: string; onChange: () => void }) {
  const { busy, error, run } = useAction();
  const patch = (body: any) => run(() => api(`${base}/${img.id}`, { method: "PATCH", body })).then(onChange);
  return (
    <figure className={`imgcard ${img.enabled ? "" : "off"}`}>
      <img src={img.preview} alt={img.card_name || "Картинка оповещения"} loading="lazy" />
      <figcaption className="stack small">
        <span>{img.kind === "card" ? (img.credit || img.card_name) : `Загружена${img.width ? ` · ${img.width}×${img.height}` : ""}`}</span>
        <select value={img.game} disabled={busy} onChange={(e) => patch({ game: e.target.value })} aria-label="Игра">
          {Object.entries(games).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="row" style={{ justifyContent: "space-between", gap: 6 }}>
          <label className="check" style={{ margin: 0 }}>
            <input type="checkbox" checked={img.enabled} disabled={busy} onChange={(e) => patch({ enabled: e.target.checked })} />
            <span>в ротации</span>
          </label>
          <span className="muted">показана {img.uses}</span>
        </span>
        <ConfirmButton className="link-btn" question="Удалить картинку?" confirmLabel="Удалить" danger disabled={busy}
          onConfirm={() => run(() => api(`${base}/${img.id}`, { method: "DELETE" })).then(onChange)}>Удалить</ConfirmButton>
        <Status error={error} />
      </figcaption>
    </figure>
  );
}

function Upload({ base, purpose, games, onDone }: { base: string; purpose: string; games: Record<string, string>; onDone: () => void }) {
  const [game, setGame] = useState("any");
  const [n, setN] = useState(0);
  const { busy, error, done, run } = useAction();
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Загрузить картинки</h3>
      <label><span>Игра</span>
        <select value={game} onChange={(e) => setGame(e.target.value)}>
          {Object.entries(games).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </label>
      <label className="btn" style={{ margin: 0, cursor: "pointer", display: "inline-flex" }}>
        {busy ? `Загружаем… ${n}` : "Выбрать файлы"}
        <input type="file" accept="image/*" multiple style={{ display: "none" }} disabled={busy} onChange={(e) => {
          const files = Array.from(e.target.files || []);
          e.target.value = "";
          if (!files.length) return;
          run(async () => {
            let i = 0;
            for (const f of files) {
              const form = new FormData();
              form.append("file", f);
              form.append("purpose", purpose);
              form.append("game", game);
              await api(base, { form });
              setN(++i);
            }
            onDone();
          }, `Загружено: ${files.length}`);
        }} />
      </label>
      <p className="muted small">JPEG, PNG или WebP до 15 МБ; сайт уменьшит до 1600 px. Лучше горизонтальные, примерно 16:9.</p>
      <Status error={error} done={done} />
    </div>
  );
}

function CardArt({ base, games, onDone }: { base: string; games: Record<string, string>; onDone: () => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const { error, done, run } = useAction();
  useEffect(() => {
    if (q.trim().length < 2) { setItems([]); return; }
    const h = setTimeout(() => {
      api<any>(`/cards/search?${new URLSearchParams({ q: q.trim(), game: "mtg", per_page: "8" })}`)
        .then((r) => setItems(r.items.filter((c: any) => c.image_url))).catch(() => setItems([]));
    }, 300);
    return () => clearTimeout(h);
  }, [q]);
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Арт карты для анонсов</h3>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Название карты или запрос: t:dragon"
        aria-label="Поиск карты" />
      <div className="artpick">
        {items.map((c) => (
          <button key={c.id} type="button" title={`Добавить арт «${c.name}»`}
            onClick={() => run(async () => { await api(`${base}/card`, { body: { card_id: c.id, game: "mtg" } }); onDone(); }, `Добавлен арт «${c.name}»`)}>
            <img src={c.image_url.replace("/normal/", "/art_crop/")} alt="" loading="lazy" />
            <span className="small">{c.name_ru || c.name}</span>
          </button>
        ))}
      </div>
      <p className="muted small">Нажмите на арт — он попадёт в пул анонсов Magic. Подпись «Арт: художник» добавится сама.</p>
      <Status error={error} done={done} />
    </div>
  );
}
