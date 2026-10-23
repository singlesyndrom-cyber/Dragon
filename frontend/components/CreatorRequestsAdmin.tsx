"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";

const FILTERS: [string, string][] = [["pending", "На рассмотрении"], ["approved", "Одобренные"], ["rejected", "Отклонённые"], ["", "Все"]];
const STATUS: Record<string, string> = { pending: "на рассмотрении", approved: "одобрена", rejected: "отклонена" };

/** Админка: заявки на статус «Создатель Клуба». Доступно администраторам и модераторам. */
export default function CreatorRequestsAdmin() {
  const [filter, setFilter] = useState("pending");
  const [rows, setRows] = useState<any[] | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const { busy, error, done, run } = useAction();
  const load = useCallback(() => api<any[]>(`/admin/creator-requests${filter ? `?status=${filter}` : ""}`)
    .then(setRows).catch(() => setRows([])), [filter]);
  useEffect(() => { load(); }, [load]);

  return (
    <section id="creator-requests">
      <h2>Заявки на статус «Создатель Клуба»</h2>
      <div className="tabs" role="tablist" aria-label="Фильтр заявок">
        {FILTERS.map(([key, label]) => (
          <button key={key || "all"} type="button" role="tab" aria-selected={filter === key} className={filter === key ? "on" : undefined}
            onClick={() => setFilter(key)}>{label}</button>
        ))}
      </div>
      <Status error={error} done={done} />
      {rows === null ? <p className="muted">Загружаем…</p> : rows.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Игрок</th><th>Email</th><th>Подана</th><th>Клуб</th><th>Статус</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.user.player_no ? <Link href={`/players/${r.user.player_no}`}>{r.user.nickname}</Link> : r.user.nickname}
                    {r.user.player_no ? <span className="muted small"> №{r.user.player_no}</span> : null}
                    {r.user.banned ? <span className="badge" style={{ marginLeft: 6 }}>заблокирован</span> : null}
                  </td>
                  <td className="small">{r.user.email || <span className="muted">нет</span>}</td>
                  <td className="small">{dateTime(r.created_at)}</td>
                  <td className="small"><b>{r.club_name}</b>{r.city ? `, ${r.city}` : ""}<div className="muted">{r.about}</div></td>
                  <td className="small">
                    {STATUS[r.status]}
                    {r.decided_by ? <div className="muted">{r.decided_by}, {dateTime(r.decided_at)}</div> : null}
                    {r.reject_reason ? <div className="muted">Причина: {r.reject_reason}</div> : null}
                    {r.status === "approved" && r.club_id ? <div><Link href={`/manage/clubs/${r.club_id}`}>Клуб создан</Link></div> : null}
                    {r.status === "approved" && !r.club_id ? (
                      <button type="button" className="small" style={{ marginTop: 4 }} disabled={busy}
                        onClick={() => run(async () => { await api(`/admin/creator-requests/${r.id}/create-club`, { method: "POST" }); await load(); },
                          `Клуб «${r.club_name}» создан, ${r.user.nickname} — организатор`)}>Создать клуб из заявки</button>
                    ) : null}
                  </td>
                  <td className="r">
                    {r.status === "pending" ? (
                      rejecting === r.id ? (
                        <form className="stack" style={{ gap: 6 }} onSubmit={(e) => {
                          e.preventDefault();
                          run(async () => { await api(`/admin/creator-requests/${r.id}/reject`, { body: { reason } }); setRejecting(null); setReason(""); await load(); },
                            `Заявка ${r.user.nickname} отклонена`);
                        }}>
                          <input placeholder="Причина (увидит игрок)" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Причина отказа" />
                          <div className="row" style={{ justifyContent: "flex-end" }}>
                            <button className="danger" disabled={busy}>Отклонить</button>
                            <button type="button" className="link-btn" onClick={() => setRejecting(null)}>Отмена</button>
                          </div>
                        </form>
                      ) : (
                        <div className="row" style={{ justifyContent: "flex-end" }}>
                          <button className="primary" disabled={busy}
                            onClick={() => run(async () => { await api(`/admin/creator-requests/${r.id}/approve`, { method: "POST" }); await load(); },
                              `${r.user.nickname} получил статус «Создатель Клуба», клуб «${r.club_name}» создан`)}>Одобрить</button>
                          <button type="button" disabled={busy} onClick={() => { setRejecting(r.id); setReason(""); }}>Отклонить</button>
                        </div>
                      )
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="muted">{filter === "pending" ? "Новых заявок нет." : "Заявок нет."}</p>}
    </section>
  );
}

/** Только администратор: модераторы и ручная выдача или снятие статуса «Создатель Клуба». */
export function StaffRoles() {
  const [staff, setStaff] = useState<any[]>([]);
  const [no, setNo] = useState("");
  const [action, setAction] = useState("mod-on");
  const { busy, error, done, run } = useAction();
  const load = useCallback(() => api<any[]>("/admin/staff").then(setStaff).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  const BODY: Record<string, any> = {
    "mod-on": { is_moderator: true }, "mod-off": { is_moderator: false },
    "creator-on": { is_club_creator: true }, "creator-off": { is_club_creator: false },
  };
  return (
    <form className="panel" onSubmit={(e) => {
      e.preventDefault();
      const n = no.replace(/\D/g, "");
      if (n) run(async () => { await api(`/admin/users/${n}/roles`, { method: "PUT", body: BODY[action] }); setNo(""); await load(); }, "Сохранено");
    }}>
      <h3>Модераторы и статусы</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Модератор рассматривает заявки «Создатель Клуба». Назначать модераторов может только администратор.</p>
      <ul className="news-list small">
        {staff.map((s) => (
          <li key={s.id} style={{ padding: "4px 0" }}>{s.nickname}{s.player_no ? ` №${s.player_no}` : ""} — {s.admin ? "администратор" : "модератор"}</li>
        ))}
      </ul>
      <label><span>Номер игрока</span><input inputMode="numeric" placeholder="1001" value={no} onChange={(e) => setNo(e.target.value)} /></label>
      <label><span>Действие</span>
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="mod-on">Назначить модератором</option>
          <option value="mod-off">Снять модератора</option>
          <option value="creator-on">Выдать статус «Создатель Клуба»</option>
          <option value="creator-off">Снять статус «Создатель Клуба»</option>
        </select>
      </label>
      <button className="primary" disabled={busy || !no.replace(/\D/g, "")}>Применить</button>
      <Status error={error} done={done} />
    </form>
  );
}
