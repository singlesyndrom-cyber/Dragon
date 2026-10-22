"use client";

import { useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { type Booking, durations, duration, freeStarts, hm, type Schedule, span } from "@/lib/booking";

/** Столы клуба карточками на выбранный день: полоса занятости, список броней и форма брони.
 *  mode "book" - игрок бронирует и отменяет свои брони; "admin" - организатор видит всех и отменяет любые. */
export default function TableSchedule({ schedule, mode, canBook, reload }: {
  schedule: Schedule; mode: "book" | "admin"; canBook: boolean; reload: () => Promise<void>;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const over = !!schedule.open && new Date(schedule.open.end).getTime() <= Date.now();   // рабочий день уже закончился
  if (!schedule.tables.length) {
    return <p className="muted">{mode === "admin" ? "Столов пока нет — добавьте первый выше." : "Клуб ещё не добавил столы."}</p>;
  }
  return (
    <>
      {schedule.open ? (
        <p className="muted small">
          Клуб работает {schedule.open.from}–{schedule.open.to}.{" "}
          {over ? "На этот день клуб уже закрыт — выберите другой день." : "Бронь — с шагом 30 минут."}
        </p>
      ) : <p className="muted">В этот день клуб не работает.</p>}
      <div className="tables-grid">
        {schedule.tables.map((t) => (
          <article key={t.id} className="table-card">
            <header>
              <h3>{t.name}</h3>
              <span className="badge">{t.seats} мест</span>
            </header>
            {t.games ? <div className="small gold">{t.games}</div> : null}
            {t.description ? <p className="muted small" style={{ margin: "4px 0 0" }}>{t.description}</p> : null}
            {schedule.open ? <Timeline schedule={schedule} bookings={t.bookings} /> : null}
            <ul className="slots">
              {t.bookings.length ? t.bookings.map((b) => (
                <li key={b.id} className={b.mine ? "mine" : undefined}>
                  <span className="num">{b.from}–{b.to}</span>
                  <span className="muted small">
                    {b.mine ? "ваша бронь" : b.nickname ? `${b.nickname}${b.player_no ? ` №${b.player_no}` : ""}` : "занято"}
                    {b.note ? ` · ${b.note}` : ""}
                  </span>
                  {b.mine || mode === "admin" ? <CancelBooking b={b} reload={reload} /> : null}
                </li>
              )) : <li className="muted small">{!schedule.open ? "—" : over ? "Броней не было" : "Броней нет — стол свободен"}</li>}
            </ul>
            {mode === "book" && canBook && schedule.open && !over ? (
              open === t.id
                ? <BookForm schedule={schedule} table={t} done={async () => { setOpen(null); await reload(); }} cancel={() => setOpen(null)} />
                : freeStarts(schedule, t.bookings).length
                  ? <button className="primary" onClick={() => setOpen(t.id)}>Забронировать</button>
                  : <p className="muted small" style={{ margin: 0 }}>Свободного времени на этот день больше нет.</p>
            ) : null}
          </article>
        ))}
      </div>
    </>
  );
}

function Timeline({ schedule, bookings }: { schedule: Schedule; bookings: Booking[] }) {
  return (
    <div className="timeline" aria-hidden="true">
      {bookings.map((b) => {
        const [left, width] = span(schedule, b);
        return <span key={b.id} className={b.mine ? "busy mine" : "busy"} style={{ left: `${left}%`, width: `${width}%` }} />;
      })}
      <span className="tl-from">{schedule.open?.from}</span><span className="tl-to">{schedule.open?.to}</span>
    </div>
  );
}

function CancelBooking({ b, reload }: { b: Booking; reload: () => Promise<void> }) {
  const { busy, error, run } = useAction();
  if (new Date(b.end).getTime() <= Date.now()) return null;
  return (
    <span>
      <ConfirmButton className="link-btn" danger disabled={busy} question={`Отменить бронь ${b.from}–${b.to}?`}
        confirmLabel="Отменить бронь" onConfirm={() => run(async () => { await api(`/bookings/${b.id}`, { method: "DELETE" }); await reload(); })}>
        отменить
      </ConfirmButton>
      <Status error={error} />
    </span>
  );
}

function BookForm({ schedule, table, done, cancel }: {
  schedule: Schedule; table: Schedule["tables"][number]; done: () => Promise<void>; cancel: () => void;
}) {
  const starts = freeStarts(schedule, table.bookings);
  const [start, setStart] = useState<number>(starts[0]);
  const durs = durations(schedule, table.bookings, start);
  const [dur, setDur] = useState<number>(Math.min(180, durs[durs.length - 1] || 30));
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  const d = durs.includes(dur) ? dur : durs[durs.length - 1];
  return (
    <form className="stack" onSubmit={(e) => {
      e.preventDefault();
      run(async () => {
        await api(`/clubs/${schedule.club_id}/bookings`, {
          body: { table_id: table.id, date: schedule.date, start: hm(start), duration: d, note: note.trim() },
        });
        await done();
      });
    }}>
      <div className="row">
        <label style={{ margin: 0 }}><span>Начало</span>
          <select value={start} onChange={(e) => setStart(+e.target.value)}>
            {starts.map((s) => <option key={s} value={s}>{hm(s)}</option>)}
          </select>
        </label>
        <label style={{ margin: 0 }}><span>На сколько</span>
          <select value={d} onChange={(e) => setDur(+e.target.value)}>
            {durs.map((x) => <option key={x} value={x}>{duration(x)} (до {hm(start + x * 60_000)})</option>)}
          </select>
        </label>
      </div>
      <label style={{ margin: 0 }}><span>Комментарий для клуба (необязательно)</span>
        <input value={note} maxLength={200} placeholder="Например: драфт на четверых" onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="row">
        <button className="primary" disabled={busy || !d}>Забронировать {hm(start)}–{hm(start + (d || 0) * 60_000)}</button>
        <button type="button" onClick={cancel}>Отмена</button>
      </div>
      <Status error={error} />
    </form>
  );
}
