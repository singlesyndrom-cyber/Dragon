/** Бронирование столов: время клуба (Москва), шаг 30 минут, свободные слоты дня. */

export const CLUB_TZ = "Europe/Moscow";
export const STEP_MIN = 30;
const MIN = 60_000;

export const WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
export const WEEKDAY_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];

/** 'ЧЧ:ММ' по времени клуба. */
export function hm(v: string | number | Date): string {
  return new Date(v).toLocaleTimeString("ru-RU", { timeZone: CLUB_TZ, hour: "2-digit", minute: "2-digit" });
}

/** Сегодня по времени клуба: 'ГГГГ-ММ-ДД'. */
export function clubToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: CLUB_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** 0 = понедельник. */
export function weekday(iso: string): number {
  return (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7;
}

export function dayLabel(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return `${WEEKDAY_SHORT[weekday(iso)]}, ${d.toLocaleDateString("ru-RU", { timeZone: "UTC", day: "numeric", month: "long" })}`;
}

export function duration(min: number): string {
  const h = Math.floor(min / 60), m = min % 60;
  return [h ? `${h} ч` : "", m ? `${m} мин` : ""].filter(Boolean).join(" ");
}

export type Booking = { id: number; start: string; end: string; from: string; to: string; mine: boolean; nickname: string | null; player_no: number | null; note: string };
export type Schedule = {
  club_id: number; date: string; weekday: string; member: boolean; step: number; max_duration: number; days_ahead: number;
  open: { from: string; to: string; start: string; end: string } | null;
  tables: { id: number; name: string; seats: number; games: string; description: string; bookings: Booking[] }[];
};

const busyAt = (bs: Booking[], from: number, to: number) =>
  bs.some((b) => new Date(b.start).getTime() < to && new Date(b.end).getTime() > from);

/** Свободные начала брони (каждые 30 минут), которые ещё не прошли и не заняты. */
export function freeStarts(s: Schedule, bookings: Booking[], now = Date.now()): number[] {
  if (!s.open) return [];
  const out: number[] = [];
  const end = new Date(s.open.end).getTime();
  for (let t = new Date(s.open.start).getTime(); t + STEP_MIN * MIN <= end; t += STEP_MIN * MIN) {
    if (t >= now && !busyAt(bookings, t, t + STEP_MIN * MIN)) out.push(t);
  }
  return out;
}

/** Возможные длительности от выбранного начала: до следующей брони, закрытия клуба или лимита. */
export function durations(s: Schedule, bookings: Booking[], start: number): number[] {
  if (!s.open) return [];
  const end = new Date(s.open.end).getTime();
  const out: number[] = [];
  for (let d = STEP_MIN; d <= s.max_duration; d += STEP_MIN) {
    if (start + d * MIN > end || busyAt(bookings, start, start + d * MIN)) break;
    out.push(d);
  }
  return out;
}

/** Доля рабочего окна для полосы занятости: [left%, width%]. */
export function span(s: Schedule, b: Booking): [number, number] {
  if (!s.open) return [0, 0];
  const a = new Date(s.open.start).getTime(), z = new Date(s.open.end).getTime();
  const from = Math.max(a, new Date(b.start).getTime()), to = Math.min(z, new Date(b.end).getTime());
  return [((from - a) / (z - a)) * 100, (Math.max(0, to - from) / (z - a)) * 100];
}

/** Часы 00:00 … 24:00 с шагом 30 минут для настроек часов работы. */
export const HALF_HOURS = Array.from({ length: 49 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
