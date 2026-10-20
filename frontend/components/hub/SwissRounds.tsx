"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

/** Туры швейцарки: переключатель туров, ввод и исправление результатов, старт / следующий тур / завершение. */
export default function SwissRounds({ t, reload }: { t: any; reload: () => Promise<void> }) {
  const [view, setView] = useState<number>(t.round || 1);
  const [loaded, setLoaded] = useState<{ round: number; items: any[] }>({ round: 0, items: [] });
  const viewRef = useRef(view);
  viewRef.current = view;
  const { busy, error, done, run } = useAction();

  useEffect(() => { if (t.round) setView(t.round); }, [t.round]);   // новый тур - сразу к нему
  const load = useCallback(() => {
    const r = view;
    if (!t.round) return;
    api<any[]>(`/tournaments/${t.id}/round/${r}`)
      .then((items) => { if (r === viewRef.current) setLoaded({ round: r, items }); }).catch(() => {});
  }, [t.id, t.round, view]);
  useEffect(load, [load]);

  const pairs = loaded.round === view ? loaded.items : [];
  const current = view === t.round;
  const pending = current ? pairs.filter((p) => p.p2 && !p.result).length : 0;
  const last = t.rounds_total && t.round >= t.rounds_total;
  const act = (path: string, msg: string) => run(() => api(path, { method: "POST" }), msg).then(async (ok) => { if (ok) await reload(); });
  const start = (force = false) => run(() => api(`/tournaments/${t.id}/start${force ? "?force=true" : ""}`, { method: "POST" }), "Турнир начался")
    .then(async (ok) => { if (ok) await reload(); });

  if (t.status === "registration") {
    const missing = t.deck_policy === "required" ? t.participants.filter((p: any) => !p.has_deck).length : 0;
    return (
      <section className="panel actions">
        <p style={{ margin: 0 }}>
          Записано игроков: {t.participants.length}. Туров: {t.rounds_total || "посчитаются автоматически по числу игроков"}.
          После старта запись закроется и появятся пары первого тура.
        </p>
        {missing ? (
          <ConfirmButton className="primary" disabled={busy || t.participants.length < 2}
            question={`Деклист не подали ${missing} игр. Начать всё равно?`} confirmLabel="Начать" onConfirm={() => start(true)}>
            Начать турнир
          </ConfirmButton>
        ) : (
          <button className="primary" disabled={busy || t.participants.length < 2} onClick={() => start()}>Начать турнир</button>
        )}
        <Status error={error} done={done} />
      </section>
    );
  }

  return (
    <section>
      <nav className="round-tabs" aria-label="Туры">
        {Array.from({ length: t.round }, (_, i) => i + 1).map((r) => (
          <button key={r} type="button" className={r === view ? "on" : undefined} aria-current={r === view ? "true" : undefined}
            onClick={() => setView(r)}>Тур {r}</button>
        ))}
        {t.rounds_total && t.round < t.rounds_total ? <span className="muted small">из {t.rounds_total}</span> : null}
      </nav>
      {!current && t.status === "running" ? (
        <p className="hint">Это прошлый тур: исправленный результат изменит таблицу, но уже составленные пары останутся прежними.</p>
      ) : null}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Стол</th><th>Игрок 1</th><th>Игрок 2</th><th>Результат</th></tr></thead>
          <tbody>
            {pairs.map((m) => (
              <tr key={m.match_id}>
                <td className="num">{m.table}</td>
                <td>{m.p1}</td>
                <td>{m.p2 ?? <span className="muted">bye</span>}</td>
                <td>
                  {m.p2 && t.status === "running" ? (
                    <select value={m.result || ""} disabled={busy} aria-label={`Результат стола ${m.table}`}
                      onChange={(e) => run(() => api(`/tournaments/matches/${m.match_id}/result`, { body: { result: e.target.value } })).then(load)}>
                      <option value="" disabled>не введён</option>
                      <option value="p1">Победа: {m.p1}</option>
                      <option value="draw">Ничья</option>
                      <option value="p2">Победа: {m.p2}</option>
                    </select>
                  ) : m.p2 ? (
                    <span className="muted">{m.result === "draw" ? "ничья" : m.result === "p1" ? `победа: ${m.p1}` : m.result === "p2" ? `победа: ${m.p2}` : "—"}</span>
                  ) : <span className="muted">победа</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {t.status === "running" && current ? (
        <>
          <p className="hint">{pending ? `Не введено результатов: ${pending}. Следующий тур откроется, когда будут введены все.` : "Все результаты тура введены."}</p>
          <div className="row">
            {!last ? <button className="primary" disabled={busy || pending > 0 || !pairs.length} onClick={() => act(`/tournaments/${t.id}/next-round`, "Пары следующего тура готовы")}>Следующий тур</button> : null}
            <ConfirmButton className={last ? "primary" : "link-btn"} disabled={busy || pending > 0 || !pairs.length}
              question={last ? "Завершить турнир? Очки уйдут в лигу клуба, отчёт — в Telegram." : `Сыграно ${t.round} из ${t.rounds_total} туров. Завершить досрочно?`}
              confirmLabel="Завершить" onConfirm={() => act(`/tournaments/${t.id}/finish`, "Турнир завершён")}>
              {last ? "Завершить турнир" : "Завершить досрочно"}
            </ConfirmButton>
          </div>
        </>
      ) : null}
      <Status error={error} done={done} />
    </section>
  );
}
