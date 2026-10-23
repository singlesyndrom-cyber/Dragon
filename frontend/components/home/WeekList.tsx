"use client";

import Link from "next/link";
import { useState } from "react";
import { dayKey, dayLabel, fill, formatLabel, liveLabel, seatsLabel, timeOf, weekDays, type HomeEvent } from "@/lib/home";

/** «Сегодня и на неделе»: полоса из семи дней и турниры. День можно выбрать, повторный клик - вся неделя. */
export default function WeekList({ events, now }: { events: HomeEvent[]; now: string }) {
  const [day, setDay] = useState<string | null>(null);
  const today = dayKey(now);
  const keyOf = (e: HomeEvent) => (e.status === "running" ? today : dayKey(e.starts_at));
  const days = weekDays(now).map((d) => ({ ...d, n: events.filter((e) => keyOf(e) === d.key).length }));
  const shown = day ? events.filter((e) => keyOf(e) === day) : events;
  return (
    <>
      <div className="h-days" role="group" aria-label="День недели">
        {days.map((d) => (
          <button key={d.key} type="button" aria-pressed={day === d.key} className={day === d.key ? "on" : ""}
            onClick={() => setDay(day === d.key ? null : d.key)}>
            <span className="small">{d.wd}</span><b className="num">{d.num}</b>
            <span className="small">{d.n ? `${d.n} турн.` : "—"}</span>
          </button>
        ))}
      </div>
      {shown.length ? (
        <ul className="h-events">
          {shown.map((e) => {
            const f = fill(e);
            return (
              <li key={e.id} className="h-card">
                <span className="h-when num"><span className="muted small">{e.status === "running" ? "Сейчас" : dayLabel(e.starts_at, now)}</span><b>{timeOf(e.starts_at)}</b></span>
                <span className="h-grow">
                  <span className="row h-title"><Link href={`/tournaments/${e.id}`}>{e.name}</Link>
                    {e.status === "running" ? <span className="h-live">{liveLabel(e)}</span> : null}</span>
                  <span className="muted small">{formatLabel(e)} · клуб «{e.club}»</span>
                </span>
                <span className="h-seats small muted">{seatsLabel(e)}
                  {f !== null ? <span className="h-bar" aria-hidden="true"><span style={{ width: `${f}%` }} /></span> : null}</span>
                <Link href={`/tournaments/${e.id}`} className="btn">{e.status === "running" ? "Смотреть" : "Записаться"}</Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="muted">{day ? "В этот день турниров нет." : "На этой неделе турниров пока нет."} <Link href="/clubs">Клубы и их расписание →</Link></p>
      )}
    </>
  );
}
