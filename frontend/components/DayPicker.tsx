"use client";

import { addDays, clubToday, dayLabel, WEEKDAY_SHORT, weekday } from "@/lib/booking";

/** Выбор дня: ближайшая неделя кнопками и календарь на весь доступный срок. */
export default function DayPicker({ value, onChange, daysAhead = 60 }: {
  value: string; onChange: (d: string) => void; daysAhead?: number;
}) {
  const today = clubToday();
  const week = Array.from({ length: 7 }, (_, i) => addDays(today, i));
  return (
    <div className="day-picker">
      <div className="day-chips" role="group" aria-label="Ближайшие дни">
        {week.map((d, i) => (
          <button key={d} type="button" className={d === value ? "chip on" : "chip"} aria-pressed={d === value} onClick={() => onChange(d)}>
            <span className="small">{i === 0 ? "сегодня" : i === 1 ? "завтра" : WEEKDAY_SHORT[weekday(d)]}</span>
            <b className="num">{+d.slice(8)}</b>
          </button>
        ))}
      </div>
      <label className="inline" style={{ margin: 0 }}>
        <span>Другая дата</span>
        <input type="date" value={value} min={today} max={addDays(today, daysAhead)} onChange={(e) => e.target.value && onChange(e.target.value)} />
      </label>
      <p className="muted small" style={{ margin: 0 }}>{dayLabel(value)}</p>
    </div>
  );
}
