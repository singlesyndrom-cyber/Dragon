"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import { Delta } from "@/components/Standings";
import { api } from "@/lib/api";
import { FORMATS, T_STATUS } from "@/lib/format";

export default function ManageTournamentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Manage id={+id} /></Guard>;
}

function Manage({ id }: { id: number }) {
  const [t, setT] = useState<any>(null);
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const load = useCallback(async () => {
    const tt = await api(`/tournaments/${id}`);
    setT(tt);
    const m = await api(`/clubs/${tt.club_id}/membership`).catch(() => null);
    setAllowed(!!m?.can_manage);
  }, [id]);
  useEffect(() => { load().catch(() => setAllowed(false)); }, [load]);

  if (allowed === null) return <p className="muted">Загружаем…</p>;
  if (!allowed || !t) return <p>Управлять турниром могут только организаторы клуба.</p>;
  return (
    <>
      <h1>{t.name}</h1>
      <p className="muted">
        {FORMATS[t.format]}, {T_STATUS[t.status]}{t.round ? `, тур ${t.round}${t.rounds_total ? ` из ${t.rounds_total}` : ""}` : ""}.{" "}
        <Link href={`/tournaments/${t.id}`}>Публичная страница</Link>
      </p>
      {t.format === "edh" ? <EdhPanel t={t} reload={load} /> : <SwissPanel t={t} reload={load} />}
      <DeckReview id={id} edh={t.format === "edh"} />
    </>
  );
}

/* ---------------- швейцарка ---------------- */
function SwissPanel({ t, reload }: { t: any; reload: () => Promise<void> }) {
  // Пары хранятся вместе с номером тура: ответ по прошлому туру, пришедший позже, не попадёт на экран
  const [loaded, setLoaded] = useState<{ round: number; items: any[] }>({ round: 0, items: [] });
  const roundRef = useRef(t.round);
  roundRef.current = t.round;
  const { busy, error, done, run } = useAction();
  const loadPairs = useCallback(() => {
    const r = t.round;
    if (!r) return;
    api<any[]>(`/tournaments/${t.id}/round/${r}`)
      .then((items) => { if (r === roundRef.current) setLoaded({ round: r, items }); })
      .catch(() => {});
  }, [t.id, t.round]);
  useEffect(loadPairs, [loadPairs]);

  const pairs = loaded.round === t.round ? loaded.items : [];
  const pending = pairs.filter((p) => p.p2 && !p.result).length;
  const last = t.rounds_total && t.round >= t.rounds_total;
  // после смены тура пары подгрузит эффект выше, по новому номеру тура
  const act = (path: string, msg: string) => run(() => api(path, { method: "POST" }), msg).then(async (ok) => {
    if (ok) await reload();
  });

  return (
    <section>
      {t.status === "registration" ? (
        <div className="panel">
          <p>Записано игроков: {t.players}. После старта регистрация закроется и появятся пары первого тура.</p>
          <button className="primary" disabled={busy || t.players < 2} onClick={() => act(`/tournaments/${t.id}/start`, "Турнир начался")}>Начать турнир</button>
        </div>
      ) : null}

      {t.status === "running" ? (
        <>
          <h2>Тур {t.round}: результаты</h2>
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
                      {m.p2 ? (
                        <select value={m.result || ""} disabled={busy} aria-label={`Результат стола ${m.table}`}
                          onChange={(e) => run(() => api(`/tournaments/matches/${m.match_id}/result`, { body: { result: e.target.value } })).then(loadPairs)}>
                          <option value="" disabled>не введён</option>
                          <option value="p1">Победа: {m.p1}</option>
                          <option value="draw">Ничья</option>
                          <option value="p2">Победа: {m.p2}</option>
                        </select>
                      ) : <span className="muted">победа</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
      {t.status === "finished" ? <p>Турнир завершён. Итоги на <Link href={`/tournaments/${t.id}`}>публичной странице</Link>.</p> : null}
      <Status error={error} done={done} />
    </section>
  );
}

/* ---------------- EDH ---------------- */
function EdhPanel({ t, reload }: { t: any; reload: () => Promise<void> }) {
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
  const checkedIn = t.participants.filter((p: any) => p.checked_in).length;

  return (
    <section>
      {t.status !== "finished" ? (
        <>
          <h2>Участники и брекеты</h2>
          <p className="muted small">Отметьте пришедших: только они попадут за столы и получат недельную надбавку +150 к банку.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Игрок</th><th>Пришёл</th><th>Брекет</th><th>Деклист</th></tr></thead>
              <tbody>
                {t.participants.map((p: any) => (
                  <tr key={p.user_id}>
                    <td>{p.nickname}</td>
                    <td><input type="checkbox" checked={p.checked_in} disabled={busy} aria-label={`${p.nickname} пришёл`}
                      onChange={(e) => run(() => api(`/edh/${t.id}/players/${p.user_id}`, { method: "PUT", body: { checked_in: e.target.checked } })).then(after)} /></td>
                    <td>
                      <select value={p.bracket} disabled={busy} aria-label={`Брекет ${p.nickname}`}
                        onChange={(e) => run(() => api(`/edh/${t.id}/players/${p.user_id}`, { method: "PUT", body: { bracket: +e.target.value } })).then(after)}>
                        {[1, 2, 3, 4, 5].map((b) => <option key={b} value={b}>{b}</option>)}
                      </select>
                    </td>
                    <td>{p.has_deck ? "подан" : <span className="muted">нет</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
            : checkedIn < 3 ? <p className="hint">Нужно минимум 3 пришедших игрока, сейчас {checkedIn}.</p> : null}
        </>
      ) : <p>Ивент завершён. Итоги на <Link href={`/tournaments/${t.id}`}>публичной странице</Link>.</p>}

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
              <select value={winners[tb.table_id] || ""} onChange={(e) => setWinners({ ...winners, [tb.table_id]: e.target.value })} aria-label="Победитель">
                <option value="">Победитель…</option>
                {tb.seats.map((s: any) => <option key={s.user_id} value={s.user_id}>{s.nickname}</option>)}
              </select>
              {tb.seconds_left > 0 ? (
                <button className="primary" disabled={busy || !winners[tb.table_id]}
                  onClick={() => run(() => api(`/edh/tables/${tb.table_id}/win`, { body: { winner_id: +winners[tb.table_id] } }), "Победа записана")
                    .then((ok) => { if (ok) loadTables(); })}>Записать победу</button>
              ) : (
                <ConfirmButton className="primary" disabled={busy || !winners[tb.table_id]}
                  question="Время стола вышло. Победа была зафиксирована до истечения таймера?" confirmLabel="Да, записать"
                  onConfirm={() => run(() => api(`/edh/tables/${tb.table_id}/win`, { body: { winner_id: +winners[tb.table_id], force: true } }), "Победа записана")
                    .then((ok) => { if (ok) loadTables(); })}>Записать победу</ConfirmButton>
              )}
              <ConfirmButton disabled={busy} question="Ничья: каждый за столом потеряет 7% банка." confirmLabel="Записать ничью"
                onConfirm={() => run(() => api(`/edh/tables/${tb.table_id}/draw`, { method: "POST" }), "Ничья записана")
                  .then((ok) => { if (ok) loadTables(); })}>Ничья</ConfirmButton>
              {tb.seconds_left <= 0 ? (
                <button disabled={busy} onClick={() => run(() => api(`/edh/tables/${tb.table_id}/timeout`, { method: "POST" }), "Стол закрыт по таймеру").then((ok) => { if (ok) loadTables(); })}>Закрыть по таймеру</button>
              ) : null}
            </div>
          ) : null}
        </div>
      ))}
      <Status error={error} done={done} />
    </section>
  );
}

/* ---------------- деклисты ---------------- */
function DeckReview({ id, edh }: { id: number; edh: boolean }) {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { api<any[]>(`/decks/tournament/${id}`).then(setRows).catch(() => {}); }, [id]);
  if (!rows.length) return null;
  return (
    <section>
      <h2>Проверка деклистов</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Игрок</th>{edh ? <><th>Командир</th><th>Брекет</th></> : null}<th>Замечания</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.user_id}>
                <td>{r.deck_id ? <Link href={`/decks/${r.deck_id}`}>{r.nickname}</Link> : r.nickname}</td>
                {edh ? <><td>{r.commanders?.join(" / ") || <span className="muted">—</span>}</td><td>{r.bracket}</td></> : null}
                <td className="small">
                  {[...(r.warnings || []), r.bracket_hint].filter(Boolean).join("; ") || <span className="muted">нет</span>}
                  {r.game_changers?.length ? <div className="muted">Game Changers: {r.game_changers.join(", ")}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
