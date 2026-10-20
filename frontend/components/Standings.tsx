import { signed } from "@/lib/format";

export type Row = { rank: number; name: string; cells: (string | number)[] };

/** Таблица с выделением призовых мест. */
export default function Standings({ head, rows, empty = "Пока нет данных" }:
  { head: string[]; rows: Row[]; empty?: string }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Место</th>
            <th>Игрок</th>
            {head.map((h) => <th key={h} className="r">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.rank + r.name} className={r.rank <= 3 ? `place-${r.rank}` : undefined}>
              <td><span className="place">{r.rank}</span></td>
              <td>{r.name}</td>
              {r.cells.map((c, i) => <td key={i} className="r">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Delta({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <span className="muted">—</span>;
  return <span className={v > 0 ? "win" : v < 0 ? "loss" : "muted"}>{signed(v)}</span>;
}
