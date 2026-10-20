"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import ArticleForm from "@/components/ArticleForm";
import ConfirmButton from "@/components/ConfirmButton";
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
          <Seasons clubId={clubId} />
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
  return (
    <section id="new-tournament" className="panel actions">
      <h2 style={{ margin: 0 }}>Новый турнир</h2>
      <p style={{ margin: 0 }} className="muted">Швейцарка, EDH-ивент или «Берсерк»: формат, сезон лиги, участники и деклисты настраиваются на следующем шаге.</p>
      <Link href={`/tournaments/new?club=${clubId}`} className="btn primary">Создать турнир</Link>
    </section>
  );
}

const KIND_LABEL: Record<string, string> = { edh: "EDH", berserk: "Берсерк" };

function Seasons({ clubId }: { clubId: number }) {
  const [items, setItems] = useState<any[]>([]);
  const [f, setF] = useState({ name: "", kind: "edh", months: "1", starts_on: "" });
  const { busy, error, done, run } = useAction();
  const load = () => api<any[]>(`/leagues?club_id=${clubId}`).then(setItems).catch(() => {});
  useEffect(() => { load(); }, [clubId]);
  const on = (k: keyof typeof f) => (e: { target: { value: string } }) => { const v = e.target.value; setF((c) => ({ ...c, [k]: v })); };
  return (
    <section>
      <h2>Сезоны лиги</h2>
      <p className="hint">
        Сезон длится 1, 2 или 3 месяца. EDH: каждый начинает сезон с банком 1000, ивенты сезона двигают этот банк.
        «Берсерк»: таблица сезона — сумма очков турниров. Ивенты привязываются к сезону при создании турнира.
      </p>
      {items.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Сезон</th><th>Формат</th><th>Даты</th><th className="r">Ивентов</th><th></th></tr></thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td><Link href={`/leagues/${l.id}`}>{l.name}</Link></td>
                  <td>{KIND_LABEL[l.kind]}</td>
                  <td className="num small">{new Date(l.starts_on).toLocaleDateString("ru-RU")} — {new Date(l.ends_on).toLocaleDateString("ru-RU")}
                    {l.status === "finished" ? <span className="badge" style={{ marginLeft: 8 }}>завершён</span>
                      : l.status === "upcoming" ? <span className="badge" style={{ marginLeft: 8 }}>скоро</span>
                      : <span className="badge live" style={{ marginLeft: 8 }}>идёт</span>}
                  </td>
                  <td className="r">{l.events}</td>
                  <td className="r">
                    {l.status !== "finished" ? (
                      <ConfirmButton className="link-btn" disabled={busy} question={`Завершить «${l.name}» досрочно? Таблица зафиксируется.`}
                        confirmLabel="Завершить" onConfirm={() => run(() => api(`/leagues/${l.id}/close`, { method: "POST" }), "Сезон завершён").then(load)}>
                        Завершить
                      </ConfirmButton>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <form className="panel" onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          await api("/leagues", { body: { club_id: clubId, name: f.name.trim(), kind: f.kind, months: +f.months, ...(f.starts_on ? { starts_on: f.starts_on } : {}) } });
          setF((c) => ({ ...c, name: "" }));
          await load();
        }, "Сезон создан");
      }}>
        <h3>Новый сезон</h3>
        <label><span>Название</span><input required minLength={2} maxLength={128} value={f.name} onChange={on("name")} placeholder="Например, Осень 2026" /></label>
        <div className="row inline">
          <label><span>Формат</span>
            <select value={f.kind} onChange={on("kind")}><option value="edh">EDH</option><option value="berserk">Берсерк</option></select>
          </label>
          <label><span>Длительность</span>
            <select value={f.months} onChange={on("months")}>
              <option value="1">1 месяц</option><option value="2">2 месяца</option><option value="3">3 месяца</option>
            </select>
          </label>
          <label><span>Начало</span><input type="date" value={f.starts_on} onChange={on("starts_on")} /></label>
        </div>
        <p className="hint">Пустая дата начала — сезон стартует сегодня.</p>
        <button className="primary" disabled={busy}>Создать сезон</button>
        <Status error={error} done={done} />
      </form>
    </section>
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
