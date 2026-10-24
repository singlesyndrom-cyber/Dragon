"use client";

import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

type Says = { nickname: string; outcome: "win" | "draw"; winner: string | null; source: string };
type Item = { table_id: number; table: number; seats: string[]; reports: Says[]; agreed: boolean; conflict: boolean;
  suggested: { outcome: string; winner: string | null } | null; in_time: boolean; overdue: boolean };

/** Для судьи EDH: кто победил за столами - по словам игроков из приложения «За столом». Обновляется каждые 5 секунд. */
export default function AppEdhReports({ tid, onApplied }: { tid: number; onApplied: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const { busy, error, done, run } = useAction();
  const load = useCallback(() => {
    api<{ items: Item[] }>(`/play/tournaments/${tid}/edh-reports`).then((x) => setItems(x.items)).catch(() => {});
  }, [tid]);
  useEffect(() => {
    load();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") load(); }, 5000);
    return () => window.clearInterval(t);
  }, [load]);
  if (!items.length) return null;
  const agreed = items.filter((i) => i.agreed).length;
  const says = (r: { outcome: string; winner: string | null }) => (r.outcome === "draw" ? "ничья" : `победил ${r.winner}`);
  const apply = (ids?: number[]) => run(async () => {
    const r = await api<{ applied: number; late_tables: number[] }>(`/play/tournaments/${tid}/edh-reports/apply`, { body: { table_ids: ids ?? null } });
    if (r.late_tables.length) throw new Error(`Стол ${r.late_tables.join(", ")}: о победе сообщили уже после таймера — решите вручную.`);
  }, "Столы закрыты").then(() => { load(); onApplied(); });

  return (
    <section className="panel app-reports" aria-live="polite">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Из приложения игроков: {items.length}</h3>
        {agreed ? <button type="button" className="primary" disabled={busy} onClick={() => apply()}>Закрыть согласованные ({agreed})</button> : null}
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Стол</th><th>Что говорят игроки</th><th>Итог</th><th /></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.table_id}>
                <td className="num">{i.table}</td>
                <td className="small">{i.reports.map((r) => <div key={r.nickname}>{r.nickname}: {says(r)}{r.source === "life" ? " ♥" : ""}</div>)}
                  <span className="muted">прислали {i.reports.length} из {i.seats.length}</span></td>
                <td>{i.agreed ? <span className="ok">совпало: {says(i.suggested!)}</span>
                  : i.conflict ? <span className="err">расходятся — разберитесь за столом</span>
                  : <span className="muted">пока один отчёт: {says(i.suggested!)}</span>}
                  {i.overdue ? <div className="small">{i.in_time ? "таймер вышел, но сообщили вовремя" : <span className="err">сообщили после таймера</span>}</div> : null}</td>
                <td>{i.suggested ? <button type="button" disabled={busy} onClick={() => apply([i.table_id])}>Закрыть стол</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Согласовано — минимум два игрока сказали одно и то же, и никто не возразил. ♥ — по счётчику жизней.</p>
      <Status error={error} done={done} />
    </section>
  );
}
