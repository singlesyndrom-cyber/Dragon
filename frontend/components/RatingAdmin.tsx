"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { TIERS } from "@/lib/rating";

/** Администратор: исключить турнир из рейтинга с причиной (или вернуть) и поправить уровень. */
export default function RatingAdmin({ tid, rated, tier }: { tid: number; rated: boolean; tier: string }) {
  const { me } = useAuth();
  const router = useRouter();
  const { busy, error, done, run } = useAction();
  const [note, setNote] = useState("");
  const [lvl, setLvl] = useState(tier);
  if (me?.role !== "admin") return null;
  const send = (body: any, msg: string) => run(async () => { await api(`/ratings/tournaments/${tid}`, { method: "PUT", body }); router.refresh(); }, msg);
  return (
    <details className="panel section">
      <summary>Рейтинг: управление (администратор)</summary>
      <div className="row inline" style={{ marginTop: 12 }}>
        <label><span>Уровень</span>
          <select value={lvl} onChange={(e) => setLvl(e.target.value)}>
            {TIERS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || lvl === tier} onClick={() => send({ rated, tier: lvl, note }, "Уровень сохранён")}>Сохранить уровень</button>
      </div>
      {rated ? (
        <div className="row inline">
          <label style={{ flex: 1 }}><span>Причина исключения (видна всем)</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="например: договорные матчи" /></label>
          <button type="button" className="danger" disabled={busy || !note.trim()} onClick={() => send({ rated: false, note }, "Турнир исключён, рейтинг пересчитан")}>Исключить из рейтинга</button>
        </div>
      ) : (
        <button type="button" disabled={busy} onClick={() => send({ rated: true }, "Турнир снова в рейтинге")}>Вернуть в рейтинг</button>
      )}
      <Status error={error} done={done} />
    </details>
  );
}
