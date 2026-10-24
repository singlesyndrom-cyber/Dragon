"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import DayPicker from "@/components/DayPicker";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import TableSchedule from "@/components/TableSchedule";
import { api } from "@/lib/api";
import { clubToday, HALF_HOURS, type Schedule, WEEKDAY_FULL } from "@/lib/booking";

export default function ManageTablesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><ManageTables clubId={+id} /></Guard>;
}

type Table = { id: number; name: string; seats: number; games: string; description: string };

function ManageTables({ clubId }: { clubId: number }) {
  const [m, setM] = useState<any>(undefined);
  const [club, setClub] = useState<any>(null);
  const [tables, setTables] = useState<Table[]>([]);
  const [day, setDay] = useState(clubToday());
  const [s, setS] = useState<Schedule | null>(null);

  useEffect(() => {
    api(`/clubs/${clubId}/membership`).then(setM).catch(() => setM(null));
    api<any[]>("/clubs").then((all) => setClub(all.find((c) => c.id === clubId) || null)).catch(() => {});
  }, [clubId]);
  const loadTables = useCallback(async () => { setTables(await api<Table[]>(`/clubs/${clubId}/tables`)); }, [clubId]);
  const loadDay = useCallback(async () => { setS(await api<Schedule>(`/clubs/${clubId}/bookings?date=${day}`)); }, [clubId, day]);
  const reload = useCallback(async () => { await Promise.all([loadTables(), loadDay()]); }, [loadTables, loadDay]);
  useEffect(() => { if (m?.can_manage) reload().catch(() => {}); }, [m, reload]);

  if (m === undefined) return <p className="muted">Загружаем…</p>;
  if (!m?.can_manage) return <p>Столами клуба управляют его организаторы.</p>;
  return (
    <>
      <p className="small" style={{ marginBottom: 4 }}><Link href={`/manage/clubs/${clubId}`}>← Управление клубом</Link></p>
      <h1>Столы {club ? `клуба «${club.name}»` : "клуба"}</h1>
      <p className="lead" style={{ marginTop: 0 }}>
        Добавьте столы и часы работы — участники клуба смогут бронировать их на странице
        {club ? <> <Link href={`/clubs/${club.slug}/tables`}>«Столы и бронирование»</Link></> : " клуба"}.
        О новых бронях и отменах бот пишет в личку тем организаторам и судьям, кого вы отметили справа.
      </p>
      <div className="split">
        <div>
          <h2>Столы</h2>
          <div className="tables-grid">
            {tables.map((t) => <TableCard key={t.id} clubId={clubId} t={t} reload={reload} />)}
            <AddTable clubId={clubId} reload={reload} />
          </div>
          <h2>Брони на день</h2>
          <DayPicker value={day} onChange={setDay} daysAhead={s?.days_ahead} />
          {s ? <TableSchedule schedule={s} mode="admin" canBook={false} reload={reload} /> : null}
        </div>
        <aside className="stack"><NotifyTest clubId={clubId} /><Hours clubId={clubId} reload={loadDay} /></aside>
      </div>
    </>
  );
}

function TableFields({ f, set }: { f: Omit<Table, "id">; set: (p: Partial<Table>) => void }) {
  return (
    <>
      <label><span>Название</span><input required maxLength={64} value={f.name} placeholder="Стол 1" onChange={(e) => set({ name: e.target.value })} /></label>
      <div className="row">
        <label style={{ margin: 0, flex: "0 0 90px" }}><span>Мест</span>
          <input type="number" min={1} max={30} value={f.seats} onChange={(e) => set({ seats: +e.target.value })} /></label>
        <label style={{ margin: 0, flex: 1 }}><span>Игры</span>
          <input maxLength={64} value={f.games} placeholder="MTG, EDH, Берсерк" onChange={(e) => set({ games: e.target.value })} /></label>
      </div>
      <label><span>Описание</span><input maxLength={300} value={f.description} placeholder="У окна, с игровым ковриком" onChange={(e) => set({ description: e.target.value })} /></label>
    </>
  );
}

const EMPTY = { name: "", seats: 4, games: "", description: "" };

function AddTable({ clubId, reload }: { clubId: number; reload: () => Promise<void> }) {
  const [f, setF] = useState(EMPTY);
  const { busy, error, run } = useAction();
  return (
    <form className="table-card add" onSubmit={(e) => {
      e.preventDefault();
      run(async () => { await api(`/clubs/${clubId}/tables`, { body: f }); setF(EMPTY); await reload(); });
    }}>
      <h3>Новый стол</h3>
      <TableFields f={f} set={(p) => setF({ ...f, ...p })} />
      <button className="primary" disabled={busy || !f.name.trim()}>Добавить стол</button>
      <Status error={error} />
    </form>
  );
}

function TableCard({ clubId, t, reload }: { clubId: number; t: Table; reload: () => Promise<void> }) {
  const [edit, setEdit] = useState<Omit<Table, "id"> | null>(null);
  const { busy, error, run } = useAction();
  if (edit) {
    return (
      <form className="table-card" onSubmit={(e) => {
        e.preventDefault();
        run(async () => { await api(`/clubs/${clubId}/tables/${t.id}`, { method: "PATCH", body: edit }); setEdit(null); await reload(); });
      }}>
        <TableFields f={edit} set={(p) => setEdit({ ...edit, ...p })} />
        <div className="row">
          <button className="primary" disabled={busy || !edit.name.trim()}>Сохранить</button>
          <button type="button" onClick={() => setEdit(null)}>Отмена</button>
        </div>
        <Status error={error} />
      </form>
    );
  }
  return (
    <article className="table-card">
      <header><h3>{t.name}</h3><span className="badge">{t.seats} мест</span></header>
      {t.games ? <div className="small gold">{t.games}</div> : null}
      {t.description ? <p className="muted small" style={{ margin: 0 }}>{t.description}</p> : null}
      <div className="row" style={{ marginTop: "auto" }}>
        <button type="button" onClick={() => setEdit({ name: t.name, seats: t.seats, games: t.games, description: t.description })}>Изменить</button>
        <ConfirmButton className="link-btn" danger disabled={busy} question={`Удалить стол «${t.name}»?`} confirmLabel="Удалить"
          onConfirm={() => run(async () => { await api(`/clubs/${clubId}/tables/${t.id}`, { method: "DELETE" }); await reload(); })}>
          удалить
        </ConfirmButton>
      </div>
      <Status error={error} />
    </article>
  );
}

const JUDGE_LABEL: Record<string, string> = { mtg: "Magic", edh: "EDH", berserk: "Берсерк", response: "Респонс" };

/** Кто получает сообщения о бронях: организаторы и судьи клуба с галочками + проверка своей лички. */
function NotifyTest({ clubId }: { clubId: number }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const list = useAction();
  const test = useAction();
  const load = useCallback(() => api<any[]>(`/clubs/${clubId}/booking-recipients`).then(setRows).catch(() => setRows([])), [clubId]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Уведомления о бронях</h3>
      <p className="muted small">Отметьте, кому бот пишет в личку о новых бронях и отменах. О своих бронях человек сообщений не получает.</p>
      {rows?.length ? (
        <ul className="news-list">
          {rows.map((r) => (
            <li key={r.user_id} style={{ padding: "8px 0" }}>
              <label className="check" style={{ margin: 0 }}>
                <input type="checkbox" checked={r.enabled} disabled={list.busy}
                  onChange={(e) => list.run(async () => {
                    await api(`/clubs/${clubId}/booking-recipients/${r.user_id}`, { method: "PUT", body: { enabled: e.target.checked } });
                    await load();
                  })} />
                <span>
                  {r.nickname}{r.me ? " (вы)" : ""}
                  <span className="muted small"> · {r.organizer ? "организатор" : `судья: ${r.judge_games.map((g: string) => JUDGE_LABEL[g] || g).join(", ")}`}</span>
                  {!r.telegram ? <span className="small" style={{ color: "var(--loss)" }}> · Telegram не привязан</span> : null}
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : rows ? <p className="muted small">Назначьте судей в управлении клубом, чтобы выбрать их получателями.</p> : null}
      <Status error={list.error} />
      <button disabled={test.busy} onClick={() => test.run(() => api(`/clubs/${clubId}/bookings/notify-test`, { method: "POST" }),
        "Отправлено: проверьте личные сообщения от бота")}>Проверить уведомления</button>
      <Status error={test.error} done={test.done} />
    </div>
  );
}

function Hours({ clubId, reload }: { clubId: number; reload: () => Promise<void> }) {
  const [days, setDays] = useState<Record<string, string[] | null> | null>(null);
  const [custom, setCustom] = useState(true);
  const { busy, error, done, run } = useAction();
  useEffect(() => {
    api(`/clubs/${clubId}/hours`).then((r) => { setDays(r.days); setCustom(r.custom); }).catch(() => {});
  }, [clubId]);
  if (!days) return null;
  const set = (d: number, v: string[] | null) => setDays({ ...days, [d]: v });
  return (
    <form className="panel hours" onSubmit={(e) => {
      e.preventDefault();
      run(async () => { await api(`/clubs/${clubId}/hours`, { method: "PUT", body: { days } }); setCustom(true); await reload(); }, "Часы работы сохранены");
    }}>
      <h3 style={{ marginTop: 0 }}>Часы работы</h3>
      {!custom ? <p className="hint" style={{ marginTop: 0 }}>Пока стоят часы по умолчанию: каждый день 10:00–23:00.</p> : null}
      {WEEKDAY_FULL.map((name, d) => {
        const v = days[d];
        return (
          <div key={d} className="hours-row">
            <label className="check" style={{ margin: 0 }}>
              <input type="checkbox" checked={!!v} onChange={(e) => set(d, e.target.checked ? ["12:00", "23:00"] : null)} />
              <span>{name}</span>
            </label>
            {v ? (
              <span className="row" style={{ gap: 6 }}>
                <select aria-label={`${name}: открытие`} value={v[0]} onChange={(e) => set(d, [e.target.value, v[1]])}>
                  {HALF_HOURS.slice(0, 48).map((h) => <option key={h}>{h}</option>)}
                </select>
                –
                <select aria-label={`${name}: закрытие`} value={v[1]} onChange={(e) => set(d, [v[0], e.target.value])}>
                  {HALF_HOURS.slice(1).map((h) => <option key={h}>{h}</option>)}
                </select>
              </span>
            ) : <span className="muted small">выходной</span>}
          </div>
        );
      })}
      <p className="hint">Если закрытие раньше открытия, клуб работает после полуночи: 18:00–02:00.</p>
      <button className="primary" disabled={busy}>Сохранить часы</button>
      <Status error={error} done={done} />
    </form>
  );
}
