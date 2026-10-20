"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { JUDGE_GAMES } from "@/lib/judges";

/** Управление клубом: судьи по направлениям. Назначение по номеру игрока, организаторы судят всё. */
export default function ClubJudges({ clubId }: { clubId: number }) {
  const [staff, setStaff] = useState<any[]>([]);
  const [no, setNo] = useState("");
  const [games, setGames] = useState<string[]>(["mtg"]);
  const { busy, error, done, run } = useAction();
  const load = () => api<any[]>(`/clubs/${clubId}/judges`).then(setStaff).catch(() => {});
  useEffect(() => { load(); }, [clubId]);
  const save = (player_no: number, g: string[], msg: string) =>
    run(async () => { await api(`/clubs/${clubId}/judges`, { method: "PUT", body: { player_no, games: g } }); await load(); }, msg);
  const toggle = (list: string[], g: string) => (list.includes(g) ? list.filter((x) => x !== g) : [...list, g]);
  const judges = staff.filter((s) => !s.organizer);

  return (
    <section className="panel judges">
      <h3>Судьи клуба</h3>
      <p className="muted small" style={{ marginTop: 0 }}>
        Судья ведёт турниры своих направлений: записывает игроков, запускает туры, вводит и исправляет результаты,
        закрывает столы EDH и завершает турнир. Создавать турниры и менять настройки клуба может только организатор.
      </p>
      {judges.length ? (
        <ul className="news-list">
          {judges.map((j) => (
            <li key={j.user_id} style={{ padding: "8px 0" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>{j.player_no ? <Link href={`/players/${j.player_no}`}>{j.nickname}</Link> : j.nickname}
                  {j.player_no ? <span className="muted small"> №{j.player_no}</span> : null}</span>
                <ConfirmButton className="link-btn" disabled={busy} question={`Снять ${j.nickname} с судейства?`} confirmLabel="Снять"
                  onConfirm={() => save(j.player_no, [], `${j.nickname} больше не судья`)}>Снять</ConfirmButton>
              </div>
              <div className="row" style={{ gap: 14 }}>
                {Object.entries(JUDGE_GAMES).map(([g, label]) => (
                  <label key={g} className="check">
                    <input type="checkbox" checked={j.games.includes(g)} disabled={busy}
                      onChange={() => { const next = toggle(j.games, g); if (next.length) save(j.player_no, next, "Направления сохранены"); }} />
                    {label}
                  </label>
                ))}
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="small">Судей пока нет.</p>}

      <form onSubmit={(e) => {
        e.preventDefault();
        const n = +no.replace(/\D/g, "");
        if (n && games.length) save(n, games, "Судья назначен").then((ok) => { if (ok) setNo(""); });
      }}>
        <label><span>Номер игрока</span><input inputMode="numeric" placeholder="1001" value={no} onChange={(e) => setNo(e.target.value)} /></label>
        <div className="row" style={{ gap: 14, marginBottom: 12 }}>
          {Object.entries(JUDGE_GAMES).map(([g, label]) => (
            <label key={g} className="check">
              <input type="checkbox" checked={games.includes(g)} onChange={() => setGames(toggle(games, g))} /> {label}
            </label>
          ))}
        </div>
        <button className="primary" disabled={busy || !no.replace(/\D/g, "") || !games.length}>Назначить судьёй</button>
      </form>
      <Status error={error} done={done} />
    </section>
  );
}
