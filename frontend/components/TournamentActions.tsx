"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function TournamentActions({ t }: { t: any }) {
  const { me, ready } = useAuth();
  const router = useRouter();
  const { busy, error, done, run } = useAction();
  const [bracket, setBracket] = useState(2);
  const [decks, setDecks] = useState<any[]>([]);
  const [deckId, setDeckId] = useState("");
  const [canManage, setCanManage] = useState(false);

  const mine = me ? t.participants.find((p: any) => p.user_id === me.id) : null;
  const open = t.status === "registration";

  useEffect(() => {
    if (!me) return;
    api(`/clubs/${t.club_id}/membership`).then((m) => setCanManage(!!m.can_manage)).catch(() => {});
    api<any[]>("/decks/mine").then((d) => setDecks(d.filter((x) => x.game === t.game))).catch(() => {});
  }, [me, t.club_id, t.game]);

  if (!ready) return null;
  if (!me) {
    return (
      <div className="panel">
        <p style={{ margin: 0 }}><Link href="/login">Войдите</Link>, чтобы записаться на турнир.</p>
      </div>
    );
  }

  return (
    <div className="panel actions">
      {canManage ? <Link href={`/manage/tournaments/${t.id}`} className="btn primary">Управлять турниром</Link> : null}
      {mine ? (
        <p style={{ margin: 0 }}>Вы записаны{t.format === "edh" ? `, брекет ${mine.bracket}` : ""}.
          {mine.has_deck ? " Деклист подан." : ""}</p>
      ) : open && !t.self_registration ? (
        <p className="muted" style={{ margin: 0 }}>На этот турнир игроков записывает организатор клуба.</p>
      ) : open && t.max_players && t.participants.length >= t.max_players ? (
        <p className="muted" style={{ margin: 0 }}>Мест нет: записано {t.max_players} из {t.max_players}.</p>
      ) : open ? (
        <>
          {t.format === "edh" ? (
            <label>
              <span>Брекет вашей колоды</span>
              <select value={bracket} onChange={(e) => setBracket(+e.target.value)}>
                {[1, 2, 3, 4, 5].map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </label>
          ) : null}
          <button className="primary" disabled={busy} onClick={() =>
            run(() => api(`/tournaments/${t.id}/register?bracket=${bracket}`, { method: "POST" }))
              .then((ok) => { if (ok) router.refresh(); })}>
            Записаться
          </button>
        </>
      ) : <p className="muted" style={{ margin: 0 }}>{t.status === "finished" ? "Турнир завершён." : "Регистрация закрыта: турнир уже идёт."}</p>}

      {mine && open && t.deck_policy !== "none" ? (
        <>
          <label>
            <span>Деклист</span>
            <select value={deckId} onChange={(e) => setDeckId(e.target.value)}>
              <option value="">Выберите колоду</option>
              {decks.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          <div className="row">
            <button disabled={!deckId || busy} onClick={() =>
              run(() => api(`/decks/${deckId}/attach/${t.id}`, { method: "PUT" }), "Деклист подан")
                .then((ok) => { if (ok) router.refresh(); })}>
              Подать деклист
            </button>
            <Link href="/me#decks" className="small">Добавить колоду</Link>
          </div>
          <button className="danger" disabled={busy} onClick={() =>
            run(() => api(`/tournaments/${t.id}/register`, { method: "DELETE" })).then((ok) => { if (ok) router.refresh(); })}>
            Отменить запись
          </button>
        </>
      ) : null}
      <Status error={error} done={done} />
    </div>
  );
}
