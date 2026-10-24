"use client";

import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

type Rep = { result: string; score: string | null; source: string; at: string } | null;
type Item = { match_id: number; table: number; p1: string; p2: string; p1_report: Rep; p2_report: Rep;
  agreed: string | null; conflict: boolean; suggested: string | null; score: string | null; applied: string | null };

/** Для судьи: результаты, которые игроки прислали из приложения «За столом». Обновляется каждые 5 секунд. */
export default function AppReports({ tid, onApplied }: { tid: number; onApplied: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const { busy, error, done, run } = useAction();
  const load = useCallback(() => {
    api<{ items: Item[] }>(`/play/tournaments/${tid}/reports`).then((x) => setItems(x.items)).catch(() => {});
  }, [tid]);
  useEffect(() => {
    load();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") load(); }, 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const open = items.filter((i) => !i.applied);
  if (!open.length) return null;
  const agreed = open.filter((i) => i.agreed).length;
  const word = (r: string | null, i: Item) => r === "draw" ? "ничья" : r === "p1" ? `победа ${i.p1}` : r === "p2" ? `победа ${i.p2}` : "—";
  const rep = (r: Rep, i: Item) => r ? <>{word(r.result, i)}{r.score ? ` ${r.score}` : ""}{r.source === "life" ? " ♥" : ""}</> : <span className="muted">ждём</span>;
  const apply = (ids?: number[]) => run(() => api(`/play/tournaments/${tid}/reports/apply`, { body: { match_ids: ids ?? null } }), "Результаты внесены")
    .then(() => { load(); onApplied(); });

  return (
    <section className="panel app-reports" aria-live="polite">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Из приложения игроков: {open.length}</h3>
        {agreed ? <button type="button" className="primary" disabled={busy} onClick={() => apply()}>Внести согласованные ({agreed})</button> : null}
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Стол</th><th>{"Игрок 1"}</th><th>{"Игрок 2"}</th><th>Итог</th><th /></tr></thead>
          <tbody>
            {open.map((i) => (
              <tr key={i.match_id}>
                <td className="num">{i.table}</td>
                <td>{i.p1}<div className="small">{rep(i.p1_report, i)}</div></td>
                <td>{i.p2}<div className="small">{rep(i.p2_report, i)}</div></td>
                <td>{i.agreed ? <span className="ok">совпало: {word(i.agreed, i)}{i.score ? ` ${i.score}` : ""}</span>
                  : i.conflict ? <span className="err">не совпало — разберитесь за столом</span>
                  : <span className="muted">прислал один игрок</span>}</td>
                <td>{i.suggested ? <button type="button" disabled={busy} onClick={() => apply([i.match_id])}>Внести</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">♥ — по счётчику жизней. Пока результат не внесён, игрок может его исправить.</p>
      <Status error={error} done={done} />
    </section>
  );
}
