import Link from "next/link";
import { plural } from "@/lib/format";

type Hist = { tournament_id: number; tournament: string; at: string; before: number; after: number; games: number; ignored: number };
export type RatingRow = {
  discipline: string; name: string; rating: number; rd: number; games: number; wins: number; draws: number; losses: number;
  peak: number; provisional: boolean; inactive: boolean; place: number | null; city_place: number | null; history: Hist[];
};

/** Линия рейтинга по турнирам (без библиотек): точки - после каждого турнира. */
function Spark({ h }: { h: Hist[] }) {
  if (h.length < 2) return null;
  const pts = [h[0].before, ...h.map((x) => x.after)];
  const lo = Math.min(...pts), hi = Math.max(...pts), span = Math.max(hi - lo, 1);
  const w = 220, ht = 48;
  const xy = pts.map((v, i) => [(i / (pts.length - 1)) * w, ht - 4 - ((v - lo) / span) * (ht - 8)]);
  return (
    <svg viewBox={`0 0 ${w} ${ht}`} className="spark" role="img" aria-label={`Рейтинг: от ${pts[0]} до ${pts[pts.length - 1]}`}>
      <polyline points={xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} fill="none" stroke="var(--gilt)" strokeWidth="2" strokeLinejoin="round" />
      <circle cx={xy[xy.length - 1][0]} cy={xy[xy.length - 1][1]} r="3" fill="var(--gilt)" />
    </svg>
  );
}

export default function RatingCards({ rows, city, need }: { rows: RatingRow[]; city: string | null; need: number }) {
  if (!rows.length) return <p className="muted">Рейтинговых партий пока нет: рейтинг появится после первого турнира с результатами.</p>;
  return (
    <div className="rating-cards">
      {rows.map((r) => {
        const last = r.history[r.history.length - 1];
        const delta = last ? last.after - last.before : 0;
        return (
          <div key={r.discipline} className="h-card">
            <span className="h-label">{r.name}</span>
            <div className="row" style={{ alignItems: "baseline" }}>
              <b className="rating-big num">{r.rating}</b>
              <span className="muted small">± {r.rd}</span>
              {delta ? <span className={delta > 0 ? "win small num" : "loss small num"}>{delta > 0 ? "+" : ""}{delta} за последний турнир</span> : null}
            </div>
            <p className="small" style={{ margin: "4px 0" }}>
              {r.provisional ? <span className="badge">предварительный: {r.games} из {need} партий</span>
                : r.inactive ? <span className="badge">не играл больше полугода</span>
                : <>Место в стране: <b className="num">{r.place ?? "—"}</b>{city ? <> · в городе {city}: <b className="num">{r.city_place ?? "—"}</b></> : null}</>}
            </p>
            <p className="muted small num" style={{ margin: 0 }}>
              {r.games} {plural(r.games, "партия", "партии", "партий")}: {r.wins}–{r.draws}–{r.losses}{!r.provisional ? ` · лучший ${r.peak}` : ""}
            </p>
            <Spark h={r.history} />
            {last ? <p className="muted small" style={{ margin: 0 }}>Последний: <Link href={`/tournaments/${last.tournament_id}`}>{last.tournament}</Link></p> : null}
          </div>
        );
      })}
    </div>
  );
}
