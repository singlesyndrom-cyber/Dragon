"use client";

import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";

/** Кабинет: заявка на статус «Создатель Клуба» и её текущий статус. */
export default function CreatorRequest() {
  const { me, reload } = useAuth();
  const [state, setState] = useState<any>(undefined);
  const [f, setF] = useState({ club_name: "", city: "", about: "" });
  const [again, setAgain] = useState(false);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api("/creator-requests/mine").then((s) => {
    setState(s);
    if (s.is_club_creator && !me?.is_club_creator) reload();   // статус выдали, пока страница была открыта
  }).catch(() => setState(null)), [me?.is_club_creator, reload]);
  useEffect(() => { load(); }, [load]);

  if (!me || me.is_club_creator || state === undefined || state === null) return null;
  const req = state.request;
  const pending = req?.status === "pending";
  const rejected = req?.status === "rejected";
  const showForm = !pending && (!rejected || again);

  return (
    <div className="panel" id="creator">
      <h3>Статус «Создатель Клуба»</h3>
      {pending ? (
        <div className="request-status">
          <p style={{ margin: 0 }}><b>Заявка отправлена, находится на рассмотрении.</b></p>
          <p className="small muted" style={{ margin: "6px 0 0" }}>
            Клуб «{req.club_name}»{req.city ? `, ${req.city}` : ""}. Подана {dateTime(req.created_at)}.
            Как только администратор её рассмотрит, статус изменится здесь; если привязан Telegram или указан email, придёт уведомление.
          </p>
          <button type="button" className="link-btn" style={{ marginTop: 8 }} onClick={() => load()}>Обновить статус</button>
        </div>
      ) : rejected ? (
        <div className="request-status">
          <p style={{ margin: 0 }}><b className="loss">Заявка отклонена</b> <span className="small muted">{dateTime(req.decided_at)}</span></p>
          {req.reject_reason ? <p className="small" style={{ margin: "6px 0 0" }}>Причина: {req.reject_reason}</p> : null}
          {!again ? <button type="button" style={{ marginTop: 10 }} onClick={() => {
            setF({ club_name: req.club_name, city: req.city, about: req.about }); setAgain(true);
          }}>Подать заявку повторно</button> : null}
        </div>
      ) : (
        <p className="small muted" style={{ marginTop: 0 }}>
          Создавать клубы на платформе могут игроки со статусом «Создатель Клуба». Расскажите о клубе, который хотите открыть:
          заявку рассмотрит администратор.
        </p>
      )}
      {showForm ? (
        <form style={{ marginTop: rejected ? 12 : 0 }} onSubmit={(e) => {
          e.preventDefault();
          run(async () => { await api("/creator-requests", { body: f }); setAgain(false); await load(); });
        }}>
          <label><span>Название будущего клуба</span><input required minLength={2} maxLength={128} value={f.club_name} onChange={(e) => setF({ ...f, club_name: e.target.value })} /></label>
          <label><span>Город</span><input maxLength={64} value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></label>
          <label><span>О клубе: где и во что будете играть, как часто</span>
            <textarea required minLength={10} maxLength={1000} value={f.about} onChange={(e) => setF({ ...f, about: e.target.value })} />
          </label>
          <button className="primary" disabled={busy}>Подать заявку на статус «Создатель Клуба»</button>
          <Status error={error} />
        </form>
      ) : null}
    </div>
  );
}
