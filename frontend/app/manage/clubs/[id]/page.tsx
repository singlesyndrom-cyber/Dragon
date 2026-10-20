"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import ArticleForm from "@/components/ArticleForm";
import Guard from "@/components/Guard";
import { api } from "@/lib/api";
import { FORMATS, T_STATUS } from "@/lib/format";

export default function ManageClubPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><ManageClub clubId={+id} /></Guard>;
}

function ManageClub({ clubId }: { clubId: number }) {
  const [m, setM] = useState<any>(undefined);
  const [club, setClub] = useState<any>(null);
  useEffect(() => {
    api(`/clubs/${clubId}/membership`).then(setM).catch(() => setM(null));
    api<any[]>("/clubs").then((all) => setClub(all.find((c) => c.id === clubId) || null)).catch(() => {});
  }, [clubId]);
  if (m === undefined) return <p className="muted">Загружаем…</p>;
  if (!m?.can_manage) return <p>Управлять клубом могут только его организаторы.</p>;
  return (
    <>
      <h1>{club ? club.name : "Клуб"}: управление</h1>
      {club ? <p><Link href={`/clubs/${club.slug}`}>Страница клуба</Link></p> : null}
      <div className="split">
        <div>
          <NewTournament clubId={clubId} />
          <ClubTournaments clubId={clubId} />
          <ArticleForm clubId={clubId} />
        </div>
        <aside><Settings clubId={clubId} initial={m.settings} /></aside>
      </div>
    </>
  );
}

function Settings({ clubId, initial }: { clubId: number; initial: any }) {
  const [f, setF] = useState({ description: initial.description || "", city: initial.city || "", telegram_chat_id: initial.telegram_chat_id || "" });
  const save = useAction();
  const test = useAction();
  return (
    <form className="panel" onSubmit={(e) => {
      e.preventDefault();
      save.run(() => api(`/clubs/${clubId}`, { method: "PATCH", body: { ...f, telegram_chat_id: f.telegram_chat_id.trim() || null } }), "Сохранено");
    }}>
      <h3>Настройки клуба</h3>
      <label><span>Город</span><input value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></label>
      <label><span>Описание</span><textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
      <label><span>ID чата или канала Telegram</span><input value={f.telegram_chat_id} placeholder="-1001234567890 или @channel" onChange={(e) => setF({ ...f, telegram_chat_id: e.target.value })} /></label>
      <p className="muted small">Добавьте бота в чат клуба и отправьте там /chatid — бот ответит нужным ID. Сюда будут приходить анонсы и итоги турниров.</p>
      <div className="row">
        <button className="primary" disabled={save.busy}>Сохранить</button>
        <button type="button" disabled={test.busy || !initial.telegram_chat_id}
          onClick={() => test.run(() => api(`/clubs/${clubId}/telegram/test`, { method: "POST" }), "Тестовое сообщение поставлено в очередь")}>
          Проверить подключение
        </button>
      </div>
      <Status error={save.error || test.error} done={save.done || test.done} />
    </form>
  );
}

function NewTournament({ clubId }: { clubId: number }) {
  const router = useRouter();
  const [f, setF] = useState({ name: "", game: "mtg", format: "swiss", rounds: "", starts_at: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const v = e.target.value;
    setF((cur) => ({ ...cur, [k]: v }));   // функциональное обновление: быстрые правки не затирают друг друга
  };
  const { busy, error, run } = useAction();
  return (
    <form id="new-tournament" onSubmit={(e) => {
      e.preventDefault();
      run(async () => {
        const body: any = { club_id: clubId, name: f.name.trim(), game: f.game, format: f.format };
        if (f.rounds && f.format !== "edh") body.rounds = +f.rounds;
        if (f.starts_at) body.starts_at = f.starts_at;   // без пояса: сервер считает его московским временем
        const r = await api("/tournaments", { body });
        router.push(`/manage/tournaments/${r.id}`);     // сразу к управлению: повторный клик не создаст дубль
      });
    }}>
      <h2 style={{ marginTop: 0 }}>Новый турнир</h2>
      <label><span>Название</span><input required minLength={2} value={f.name} onChange={set("name")} /></label>
      <div className="row inline">
        <label><span>Игра</span>
          <select value={f.game} onChange={set("game")}>
            <option value="mtg">Magic: The Gathering</option><option value="berserk">Берсерк</option>
          </select>
        </label>
        <label><span>Формат</span>
          <select value={f.format} onChange={set("format")}>
            {Object.entries(FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {f.format !== "edh" ? (
          <label><span>Туров</span>
            <input type="number" min={1} max={15} placeholder={f.format === "fast_swiss" ? "1" : "авто"} value={f.rounds} onChange={set("rounds")} style={{ width: 90 }} />
          </label>
        ) : null}
        <label><span>Начало</span><input type="datetime-local" value={f.starts_at} onChange={set("starts_at")} /></label>
      </div>
      <p className="hint">
        {f.format === "edh" ? "Столы по 3–5 игроков, 70 минут на партию, рассадка по брекетам."
          : f.format === "fast_swiss" ? "Обычно один тур. Пустое поле — 1 тур."
          : "Пустое поле «Туров» — число туров посчитается по числу игроков при старте."}
      </p>
      <button className="primary" disabled={busy}>Создать турнир</button>
      <Status error={error} />
    </form>
  );
}

function ClubTournaments({ clubId }: { clubId: number }) {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { api<any[]>(`/tournaments?club_id=${clubId}&limit=30`).then(setItems).catch(() => {}); }, [clubId]);
  if (!items.length) return null;
  return (
    <section>
      <h2>Турниры клуба</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Турнир</th><th>Формат</th><th>Статус</th><th className="r">Игроков</th></tr></thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id}>
                <td><Link href={`/manage/tournaments/${t.id}`}>{t.name}</Link></td>
                <td>{FORMATS[t.format]}</td>
                <td>{T_STATUS[t.status]}</td>
                <td className="r">{t.players}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
