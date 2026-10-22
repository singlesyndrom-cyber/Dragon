"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import DayPicker from "@/components/DayPicker";
import { Status, useAction } from "@/components/Form";
import TableSchedule from "@/components/TableSchedule";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { clubToday, type Schedule } from "@/lib/booking";

export default function ClubTablesPage({ params }: { params: Promise<{ slug: string }> }) {
  const slug = decodeURIComponent(use(params).slug);
  const { me, ready } = useAuth();
  const [club, setClub] = useState<any>(undefined);
  const [day, setDay] = useState(clubToday());
  const [s, setS] = useState<Schedule | null>(null);
  const [mine, setMine] = useState<any[]>([]);
  const join = useAction();

  useEffect(() => { api(`/clubs/${encodeURIComponent(slug)}`).then(setClub).catch(() => setClub(null)); }, [slug]);
  const load = useCallback(async () => {
    if (!club) return;
    setS(await api<Schedule>(`/clubs/${club.id}/bookings?date=${day}`));
    if (me) setMine((await api<any[]>("/bookings/mine")).filter((b) => b.club_id === club.id));
  }, [club, day, me]);
  useEffect(() => { load().catch(() => setS(null)); }, [load]);

  if (club === undefined || !ready) return <p className="muted">Загружаем…</p>;
  if (!club) return <p>Клуб не найден.</p>;
  return (
    <>
      <p className="small" style={{ marginBottom: 4 }}><Link href={`/clubs/${club.slug}`}>← {club.name}</Link></p>
      <h1>Столы и бронирование</h1>
      {!me ? (
        <div className="panel"><Link href="/login">Войдите</Link>, чтобы забронировать стол. Занятость видна и без входа.</div>
      ) : s && !s.member ? (
        <div className="panel row">
          <span>Бронировать могут участники клуба.</span>
          <button className="primary" disabled={join.busy}
            onClick={() => join.run(() => api(`/clubs/${club.id}/join`, { method: "POST" })).then((ok) => { if (ok) load(); })}>
            Вступить в клуб
          </button>
          <Status error={join.error} />
        </div>
      ) : null}

      {mine.length ? (
        <section className="panel" style={{ marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Ваши брони</h3>
          <ul className="news-list">
            {mine.map((b) => (
              <li key={b.id} style={{ padding: "8px 0" }}>
                <b>{b.table}</b> · <span className="num">{b.when}</span>
                {b.note ? <span className="muted small"> · {b.note}</span> : null}
              </li>
            ))}
          </ul>
          <p className="hint">Отменить бронь можно в карточке стола на нужный день или в личном кабинете.</p>
        </section>
      ) : null}

      <section className="section">
        <DayPicker value={day} onChange={setDay} daysAhead={s?.days_ahead} />
        {s ? <TableSchedule schedule={s} mode="book" canBook={!!me && s.member} reload={load} /> : <p className="muted">Загружаем…</p>}
      </section>
    </>
  );
}
