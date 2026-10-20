"use client";

import { useEffect, useRef, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

/** Участники: добавить по имени (гость) или из игроков клуба, отметка прихода и брекет (EDH),
 *  удаление до старта, «выбыл» во время турнира, привязка гостя к аккаунту. */
export default function Participants({ t, reload }: { t: any; reload: () => Promise<void> }) {
  const edh = t.format === "edh";
  const [q, setQ] = useState("");
  const [hints, setHints] = useState<any[]>([]);
  const [bracket, setBracket] = useState(2);
  const [mergeFor, setMergeFor] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const { busy, error, done, run } = useAction();

  const canAdd = t.status === "registration" || (edh && t.status === "running");
  const inList = new Set(t.participants.map((p: any) => p.user_id));

  useEffect(() => {
    if (!q.trim()) { setHints([]); return; }
    const h = setTimeout(() => {
      api<any[]>(`/clubs/${t.club_id}/players?q=${encodeURIComponent(q.trim())}`)
        .then((r) => setHints(r.filter((x) => !inList.has(x.user_id)).slice(0, 6))).catch(() => setHints([]));
    }, 200);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, t.club_id, t.participants.length]);

  const add = (body: any, label: string) => run(async () => {
    await api(`/tournaments/${t.id}/players`, { body: { ...body, bracket } });
    setQ(""); setHints([]);
    await reload();
    input.current?.focus();
  }, `${label}: добавлен`);

  const exact = hints.find((h) => h.nickname.toLowerCase() === q.trim().toLowerCase());
  const checked = t.participants.filter((p: any) => p.checked_in && !p.dropped).length;

  return (
    <section>
      {canAdd ? (
        <form className="add-player" onSubmit={(e) => {
          e.preventDefault();
          if (!q.trim()) return;
          if (exact) add({ user_id: exact.user_id }, exact.nickname); else add({ nickname: q.trim() }, q.trim());
        }}>
          <label style={{ flex: 1, margin: 0 }}>
            <span>Добавить игрока: имя из клуба или новое — тогда это гость без аккаунта</span>
            <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" placeholder="Например, Алексей" />
          </label>
          {edh ? (
            <label style={{ margin: 0 }}><span>Брекет</span>
              <select value={bracket} onChange={(e) => setBracket(+e.target.value)}>
                {[1, 2, 3, 4, 5].map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </label>
          ) : null}
          <button className="primary" disabled={busy || !q.trim()}>{exact ? "Добавить" : "Добавить гостя"}</button>
          {hints.length ? (
            <div className="hints" role="listbox" aria-label="Игроки клуба">
              {hints.map((h) => (
                <button type="button" key={h.user_id} role="option" aria-selected={false}
                  onClick={() => add({ user_id: h.user_id }, h.nickname)}>
                  {h.nickname}{h.guest ? <span className="badge" style={{ marginLeft: 8 }}>гость</span> : null}
                </button>
              ))}
            </div>
          ) : null}
        </form>
      ) : null}
      <Status error={error} done={done} />

      <p className="hint">
        {t.participants.length} {t.max_players ? `из ${t.max_players} ` : ""}участников
        {edh ? `, пришли ${checked}. Отметьте пришедших: только они сядут за столы и получат недельную надбавку +150.` : "."}
        {!t.self_registration ? " Игроки не могут записаться сами — добавляйте их здесь." : ""}
      </p>
      {t.participants.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Игрок</th>
                {edh ? <><th>Пришёл</th><th>Брекет</th></> : null}
                {t.deck_policy !== "none" ? <th>Деклист</th> : null}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {t.participants.map((p: any) => (
                <tr key={p.user_id} className={p.dropped ? "dropped" : undefined}>
                  <td>
                    {p.nickname}
                    {p.guest ? <span className="badge" style={{ marginLeft: 8 }}>гость</span> : null}
                    {p.dropped ? <span className="badge" style={{ marginLeft: 8 }}>выбыл</span> : null}
                  </td>
                  {edh ? (
                    <>
                      <td><input type="checkbox" checked={p.checked_in} disabled={busy || t.status === "finished"} aria-label={`${p.nickname} пришёл`}
                        onChange={(e) => run(() => api(`/edh/${t.id}/players/${p.user_id}`, { method: "PUT", body: { checked_in: e.target.checked } })).then(reload)} /></td>
                      <td>
                        <select value={p.bracket} disabled={busy || t.status === "finished"} aria-label={`Брекет ${p.nickname}`}
                          onChange={(e) => run(() => api(`/edh/${t.id}/players/${p.user_id}`, { method: "PUT", body: { bracket: +e.target.value } })).then(reload)}>
                          {[1, 2, 3, 4, 5].map((b) => <option key={b} value={b}>{b}</option>)}
                        </select>
                      </td>
                    </>
                  ) : null}
                  {t.deck_policy !== "none" ? (
                    <td>{p.has_deck ? "подан" : <span className={t.deck_policy === "required" ? "loss" : "muted"}>нет</span>}</td>
                  ) : null}
                  <td className="r">
                    <div className="row" style={{ justifyContent: "flex-end", gap: 12 }}>
                      {p.guest ? (
                        mergeFor === p.user_id ? (
                          <form className="row inline" onSubmit={(e) => {
                            e.preventDefault();
                            run(async () => {
                              await api(`/clubs/${t.club_id}/guests/${p.user_id}/merge`, { body: { email } });
                              setMergeFor(null); setEmail(""); await reload();
                            }, "История гостя перенесена на аккаунт");
                          }}>
                            <input type="email" required placeholder="email аккаунта" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email аккаунта игрока" />
                            <button className="primary" disabled={busy}>Привязать</button>
                            <button type="button" onClick={() => setMergeFor(null)}>Отмена</button>
                          </form>
                        ) : <button type="button" className="link-btn" onClick={() => setMergeFor(p.user_id)}>Привязать аккаунт</button>
                      ) : null}
                      {t.status === "registration" ? (
                        <button type="button" className="link-btn" disabled={busy}
                          onClick={() => run(() => api(`/tournaments/${t.id}/players/${p.user_id}`, { method: "DELETE" })).then(reload)}>Убрать</button>
                      ) : t.status === "running" ? (
                        p.dropped ? (
                          <button type="button" className="link-btn" disabled={busy}
                            onClick={() => run(() => api(`/tournaments/${t.id}/players/${p.user_id}/drop`, { body: { dropped: false } })).then(reload)}>Вернуть</button>
                        ) : (
                          <ConfirmButton className="link-btn" disabled={busy} question={`${p.nickname} выбывает: в следующих турах без пар.`}
                            confirmLabel="Снять" onConfirm={() => run(() => api(`/tournaments/${t.id}/players/${p.user_id}/drop`, { body: { dropped: true } })).then(reload)}>
                            Выбыл
                          </ConfirmButton>
                        )
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">Пока никого. Добавьте игроков выше{t.self_registration ? " или дождитесь, пока они запишутся сами по ссылке на турнир" : ""}.</p>}
    </section>
  );
}
