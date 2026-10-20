"use client";

import { useCallback, useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import { Delta } from "@/components/Standings";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";

/** EDH: рассадка, таймеры столов, победа / ничья / таймаут, завершение ивента. */
export default function EdhTables({ t, reload }: { t: any; reload: () => Promise<void> }) {
  const [tables, setTables] = useState<any[]>([]);
  const [winners, setWinners] = useState<Record<number, string>>({});
  const { busy, error, done, run } = useAction();
  const loadTables = useCallback(() => {
    if (t.round) api<any[]>(`/edh/${t.id}/tables`).then(setTables).catch(() => {});
  }, [t.id, t.round]);
  useEffect(() => {
    loadTables();
    const h = setInterval(loadTables, 30000);   // таймеры столов обновляются каждые 30 секунд
    return () => clearInterval(h);
  }, [loadTables]);

  const open = tables.filter((x) => x.status === "playing").length;
  const after = async (ok: boolean) => { if (ok) { await reload(); loadTables(); } };
  const checkedIn = t.participants.filter((p: any) => p.checked_in && !p.dropped).length;
  const closeTable = (path: string, body: any, msg: string) =>
    run(() => api(path, body ? { body } : { method: "POST" }), msg).then((ok) => { if (ok) loadTables(); });

  return (
    <section>
      {t.status !== "finished" ? (
        <div className="panel actions">
          <p style={{ margin: 0 }}>
            {t.round ? `Идёт тур ${t.round}.` : "Ивент ещё не начат."} Пришли {checkedIn} {plural(checkedIn, "игрок", "игрока", "игроков")}.
            Столы по 3–5 человек, рассадка случайная внутри брекетов, 70 минут на партию.
          </p>
          <div className="row">
            <button className="primary" disabled={busy || open > 0 || checkedIn < 3}
              onClick={() => run(() => api(`/edh/${t.id}/round`, { method: "POST" }), "Рассадка готова, таймер 70 минут запущен").then(after)}>
              {t.round ? "Новый тур: рассадить заново" : "Рассадить и начать"}
            </button>
            {t.status === "running" ? (
              <ConfirmButton disabled={busy || open > 0} question="Завершить ивент? Итоги уйдут в Telegram-чат клуба."
                confirmLabel="Завершить" onConfirm={() => run(() => api(`/edh/${t.id}/finish`, { method: "POST" }), "Ивент завершён").then(after)}>
                Завершить ивент
              </ConfirmButton>
            ) : null}
          </div>
          {open > 0 ? <p className="hint">Новый тур и завершение станут доступны, когда все столы текущего тура будут закрыты.</p>
            : checkedIn < 3 ? <p className="hint">Нужно минимум 3 пришедших игрока: отметьте их на вкладке «Участники».</p> : null}
        </div>
      ) : null}

      {tables.length ? <h2>Столы, тур {t.round}</h2> : null}
      {tables.map((tb) => (
        <div key={tb.table_id} className="panel">
          <div className="row">
            <h3 style={{ margin: 0 }}>Стол {tb.table}</h3>
            <span className="badge">брекет {tb.bracket}</span>
            {tb.status === "playing"
              ? <span className={tb.seconds_left > 0 ? "badge live" : "badge"}>{tb.seconds_left > 0 ? `осталось ${Math.ceil(tb.seconds_left / 60)} мин` : "время вышло"}</span>
              : <span className="badge">{tb.outcome === "win" ? "победа" : tb.outcome === "draw" ? "ничья" : "истекло время"}</span>}
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Игрок</th><th className="r">Банк</th><th className="r">Изменение</th></tr></thead>
              <tbody>
                {tb.seats.map((s: any) => (
                  <tr key={s.user_id} className={tb.outcome === "win" && s.delta > 0 ? "winner" : undefined}>
                    <td>{s.nickname}{tb.outcome === "win" && s.delta > 0 ? ", победитель" : ""}</td>
                    <td className="r">{Math.round(s.bank_after ?? s.bank_before)}</td><td className="r"><Delta v={s.delta} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {tb.status === "playing" ? (
            <div className="row inline">
              <select value={winners[tb.table_id] || ""} onChange={(e) => { const v = e.target.value; setWinners((w) => ({ ...w, [tb.table_id]: v })); }} aria-label={`Победитель стола ${tb.table}`}>
                <option value="">Победитель…</option>
                {tb.seats.map((s: any) => <option key={s.user_id} value={s.user_id}>{s.nickname}</option>)}
              </select>
              {tb.seconds_left > 0 ? (
                <button className="primary" disabled={busy || !winners[tb.table_id]}
                  onClick={() => closeTable(`/edh/tables/${tb.table_id}/win`, { winner_id: +winners[tb.table_id] }, "Победа записана")}>Записать победу</button>
              ) : (
                <ConfirmButton className="primary" disabled={busy || !winners[tb.table_id]}
                  question="Время стола вышло. Победа была зафиксирована до истечения таймера?" confirmLabel="Да, записать"
                  onConfirm={() => closeTable(`/edh/tables/${tb.table_id}/win`, { winner_id: +winners[tb.table_id], force: true }, "Победа записана")}>Записать победу</ConfirmButton>
              )}
              <ConfirmButton disabled={busy} question="Ничья: каждый за столом потеряет 7% банка." confirmLabel="Записать ничью"
                onConfirm={() => closeTable(`/edh/tables/${tb.table_id}/draw`, null, "Ничья записана")}>Ничья</ConfirmButton>
              {tb.seconds_left <= 0 ? (
                <button disabled={busy} onClick={() => closeTable(`/edh/tables/${tb.table_id}/timeout`, null, "Стол закрыт по таймеру")}>Закрыть по таймеру</button>
              ) : null}
            </div>
          ) : null}
        </div>
      ))}
      <Status error={error} done={done} />
    </section>
  );
}
