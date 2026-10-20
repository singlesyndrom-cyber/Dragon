"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import TournamentFields, { EMPTY, type Fields, toBody } from "@/components/TournamentFields";
import { api } from "@/lib/api";
import { KINDS } from "@/lib/tournamentKinds";

export default function NewTournamentPage() {
  return <Guard><Suspense fallback={<p className="muted">Загружаем…</p>}><Wizard /></Suspense></Guard>;
}

function Wizard() {
  const router = useRouter();
  const sp = useSearchParams();
  const [clubs, setClubs] = useState<any[] | null>(null);
  const [clubId, setClubId] = useState<string>(sp.get("club") || "");
  const [kindKey, setKindKey] = useState<string>(sp.get("kind") || "");
  const [allSeasons, setAllSeasons] = useState<any[]>([]);
  const [f, setF] = useState<Fields>(EMPTY);
  const set = (patch: Partial<Fields>) => setF((cur) => ({ ...cur, ...patch }));
  const { busy, error, run } = useAction();

  useEffect(() => {
    api<any[]>("/clubs/managed").then((c) => {
      setClubs(c);
      if (!clubId && c.length === 1) setClubId(String(c[0].id));
    }).catch(() => setClubs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    setAllSeasons([]);
    if (clubId) api<any[]>(`/leagues?club_id=${clubId}`).then(setAllSeasons).catch(() => {});
  }, [clubId]);

  const kind = KINDS.find((k) => k.key === kindKey);
  const seasons = useMemo(
    () => (kind?.league ? allSeasons.filter((s) => s.kind === kind.league && s.status !== "finished") : null),
    [allSeasons, kind],
  );
  // один активный сезон подходящего вида - выбираем его сразу: так организатор не забудет привязать ивент
  useEffect(() => {
    if (!seasons) { set({ league_id: "" }); return; }
    const active = seasons.filter((s) => s.status === "active");
    set({ league_id: active.length === 1 ? String(active[0].id) : "" });
  }, [seasons]);
  useEffect(() => {
    if (kind && kind.format === "fast_swiss") set({ rounds: "1" });
    if (kind && kind.format === "edh") set({ rounds: "" });
  }, [kind]);

  if (clubs === null) return <p className="muted">Загружаем…</p>;
  if (!clubs.length) {
    return (
      <>
        <h1>Новый турнир</h1>
        <p className="lead">Турниры проводят клубы. Создайте клуб — вы станете его организатором.</p>
        <Link href="/clubs/new" className="btn primary">Создать клуб</Link>
      </>
    );
  }

  return (
    <>
      <h1>Новый турнир</h1>
      <form className="wizard" onSubmit={(e) => {
        e.preventDefault();
        if (!kind) return;
        run(async () => {
          const r = await api("/tournaments", { body: { club_id: +clubId, game: kind.game, format: kind.format, ...toBody(f, kind.format) } });
          router.push(`/manage/tournaments/${r.id}`);
        });
      }}>
        <fieldset>
          <legend>Клуб</legend>
          {clubs.length === 1 ? <p style={{ margin: 0 }}>{clubs[0].name}</p> : (
            <select value={clubId} onChange={(e) => setClubId(e.target.value)} required aria-label="Клуб">
              <option value="" disabled>Выберите клуб</option>
              {clubs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </fieldset>

        <fieldset>
          <legend>Игра и формат</legend>
          <div className="kinds" role="radiogroup" aria-label="Игра и формат">
            {KINDS.map((k) => (
              <label key={k.key} className={"kind" + (k.key === kindKey ? " on" : "")}>
                <input type="radio" name="kind" value={k.key} checked={k.key === kindKey} onChange={() => setKindKey(k.key)} />
                <b>{k.title}</b>
                <span className="muted small">{k.text}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {kind && clubId ? (
          <>
            <TournamentFields f={f} set={set} format={kind.format} seasons={seasons} />
            <div className="row">
              <button className="primary" disabled={busy}>Создать турнир</button>
              <span className="hint" style={{ margin: 0 }}>Дальше откроется страница турнира: участники, туры и таблица.</span>
            </div>
          </>
        ) : <p className="hint">Выберите {clubId ? "" : "клуб и "}формат — появятся остальные настройки.</p>}
        <Status error={error} />
      </form>
    </>
  );
}
