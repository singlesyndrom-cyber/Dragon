"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import { api } from "@/lib/api";
import { dateOnly, dateTime } from "@/lib/format";
import { canRun } from "@/lib/judges";
import { kindOf } from "@/lib/tournamentKinds";

export default function ClubMembersPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Members clubId={+id} /></Guard>;
}

type Row = {
  user_id: number; nickname: string; player_no: number | null; guest: boolean; organizer: boolean; judge_games: string[];
  league_points: number; edh_bank: number; events_played: number; joined_at: string; last_played: string | null;
  telegram: boolean; registered: boolean;
};
type SortKey = "nickname" | "league_points" | "edh_bank" | "events_played" | "last_played" | "joined_at";
const JUDGE: Record<string, string> = { mtg: "Magic", edh: "EDH", berserk: "Берсерк", response: "Респонс" };
const COLS: [SortKey, string][] = [
  ["nickname", "Игрок"], ["league_points", "Очки лиги"], ["edh_bank", "Банк EDH"], ["events_played", "Ивентов"],
  ["last_played", "Последняя игра"], ["joined_at", "В клубе с"],
];

function Members({ clubId }: { clubId: number }) {
  const [m, setM] = useState<any>(undefined);
  const [club, setClub] = useState<any>(null);
  const [tours, setTours] = useState<any[]>([]);
  const [tid, setTid] = useState<number | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<[SortKey, boolean]>(["nickname", true]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [bracket, setBracket] = useState(2);
  const add = useAction();
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api(`/clubs/${clubId}/membership`).then(setM).catch(() => setM(null));
    api<any[]>("/clubs").then((all) => setClub(all.find((c) => c.id === clubId) || null)).catch(() => {});
  }, [clubId]);
  const staff = !!m && (m.can_manage || (m.judge_games || []).length > 0);

  // турниры, куда можно записывать: идёт запись (EDH - и во время игры, опоздавшие) и этот человек их ведёт
  useEffect(() => {
    if (!staff) return;
    api<any[]>(`/tournaments?club_id=${clubId}&limit=50`).then((all) => {
      const open = all.filter((t) => (t.status === "registration" || (t.status === "running" && t.format === "edh")) && canRun(m, t))
        .sort((a, b) => +new Date(a.starts_at) - +new Date(b.starts_at));
      setTours(open);
      setTid((cur) => cur ?? open[0]?.id ?? null);
    }).catch(() => {});
  }, [staff, clubId, m]);

  const load = useCallback(async () => {
    setRows(await api<Row[]>(`/clubs/${clubId}/members${tid ? `?tournament_id=${tid}` : ""}`));
  }, [clubId, tid]);
  useEffect(() => { if (staff) load().catch(() => setRows([])); }, [staff, load]);
  useEffect(() => { setPicked(new Set()); }, [tid]);

  const tour = tours.find((t) => t.id === tid) || null;
  const shown = useMemo(() => {
    const term = q.trim().toLowerCase().replace(/^[№#]/, "");
    const list = (rows || []).filter((r) => !term || r.nickname.toLowerCase().includes(term) || String(r.player_no ?? "") === term);
    const [key, asc] = sort;
    const val = (r: Row) => key === "nickname" ? r.nickname.toLowerCase()
      : key === "last_played" || key === "joined_at" ? (r[key] ? +new Date(r[key] as string) : 0) : r[key];
    return [...list].sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (asc ? 1 : -1));
  }, [rows, q, sort]);

  if (m === undefined) return <p className="muted">Загружаем…</p>;
  if (!staff) return <p>Список участников видят организаторы и судьи клуба.</p>;

  const enroll = (ids: number[]) => {
    setMsg("");
    add.run(async () => {
      if (!tour) return;
      const r = await api<any>(`/tournaments/${tour.id}/players/bulk`, { body: { user_ids: ids, bracket } });
      setPicked(new Set());
      await load();
      const parts = [`Записано: ${r.added.length}`];
      if (r.no_room.length) parts.push(`не хватило мест: ${r.no_room.length}`);
      if (r.skipped.length) parts.push(`уже были в турнире: ${r.skipped.length}`);
      setMsg(parts.join(", "));
    });
  };
  const free = tour?.max_players ? Math.max(0, tour.max_players - (rows || []).filter((r) => r.registered).length) : null;
  const toggle = (id: number) => setPicked((cur) => {
    const n = new Set(cur);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const selectable = shown.filter((r) => !r.registered);
  const edh = tour?.format === "edh";

  return (
    <>
      <p className="small" style={{ marginBottom: 4 }}>
        {m.can_manage ? <Link href={`/manage/clubs/${clubId}`}>← Управление клубом</Link> : <Link href="/me">← Кабинет</Link>}
      </p>
      <h1>Участники {club ? `клуба «${club.name}»` : "клуба"}</h1>
      <p className="lead" style={{ marginTop: 0 }}>
        Все, кто вступил в клуб или играл в нём. Выберите турнир и запишите игроков кнопкой в строке или отметьте нескольких.
      </p>

      <section className="panel members-bar">
        <label style={{ margin: 0 }}>
          <span>Записывать в турнир</span>
          {tours.length ? (
            <select value={tid ?? ""} onChange={(e) => setTid(+e.target.value)}>
              {tours.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {dateTime(t.starts_at)} · {kindOf(t.game, t.format, t.draft)?.title || t.format}{t.status === "running" ? " (идёт)" : ""}
                </option>
              ))}
            </select>
          ) : <span className="muted small">Нет турниров с открытой записью, которые вы ведёте. <Link href={`/tournaments/new?club=${clubId}`}>Создать турнир</Link></span>}
        </label>
        {tour ? (
          <>
            {edh ? (
              <label style={{ margin: 0 }}>
                <span>Брекет</span>
                <select value={bracket} onChange={(e) => setBracket(+e.target.value)}>
                  {[1, 2, 3, 4, 5].map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              </label>
            ) : null}
            <span className="muted small">
              Записано {(rows || []).filter((r) => r.registered).length}{tour.max_players ? ` из ${tour.max_players}` : ""}
              {free !== null ? `, свободно ${free}` : ""} · <Link href={`/manage/tournaments/${tour.id}`}>к турниру</Link>
            </span>
            <button className="primary" disabled={add.busy || !picked.size}
              onClick={() => enroll(shown.filter((r) => picked.has(r.user_id)).map((r) => r.user_id))}>
              Записать отмеченных{picked.size ? ` (${picked.size})` : ""}
            </button>
          </>
        ) : null}
        <Status error={add.error} done={msg} />
      </section>

      <div className="row" style={{ margin: "16px 0 0" }}>
        <input type="search" placeholder="Поиск по нику или номеру" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 320 }} />
        <span className="muted small">{rows ? `Участников: ${rows.length}${q ? `, найдено: ${shown.length}` : ""}` : "Загружаем…"}</span>
      </div>

      {rows ? (
        <div className="table-wrap">
          <table className="members">
            <thead>
              <tr>
                {tour ? (
                  <th style={{ width: 28 }}>
                    <input type="checkbox" aria-label="Отметить всех незаписанных"
                      checked={!!selectable.length && selectable.every((r) => picked.has(r.user_id))}
                      onChange={(e) => setPicked(e.target.checked ? new Set(selectable.map((r) => r.user_id)) : new Set())} />
                  </th>
                ) : null}
                {COLS.map(([key, label]) => (
                  <th key={key} className={key === "nickname" ? undefined : "r"}>
                    <button type="button" className="link-btn sort" onClick={() => setSort(([k, a]) => [key, k === key ? !a : key === "nickname"])}>
                      {label}{sort[0] === key ? (sort[1] ? " ↑" : " ↓") : ""}
                    </button>
                  </th>
                ))}
                <th>Telegram</th>
                {tour ? <th></th> : null}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.user_id}>
                  {tour ? (
                    <td>
                      <input type="checkbox" aria-label={`Отметить ${r.nickname}`} disabled={r.registered}
                        checked={picked.has(r.user_id)} onChange={() => toggle(r.user_id)} />
                    </td>
                  ) : null}
                  <td>
                    {r.player_no ? <Link href={`/players/${r.player_no}`}>{r.nickname}</Link> : r.nickname}
                    {r.player_no ? <span className="muted small"> №{r.player_no}</span> : null}
                    {r.organizer ? <span className="badge" style={{ marginLeft: 6 }}>организатор</span> : null}
                    {r.judge_games.length ? <span className="badge" style={{ marginLeft: 6 }}>судья: {r.judge_games.map((g) => JUDGE[g] || g).join(", ")}</span> : null}
                    {r.guest ? <span className="badge" style={{ marginLeft: 6 }}>гость</span> : null}
                  </td>
                  <td className="r num">{r.league_points}</td>
                  <td className="r num">{Math.round(r.edh_bank).toLocaleString("ru-RU")}</td>
                  <td className="r num">{r.events_played}</td>
                  <td className="r small">{r.last_played ? dateOnly(r.last_played) : <span className="muted">—</span>}</td>
                  <td className="r small">{dateOnly(r.joined_at)}</td>
                  <td className="small">{r.guest ? <span className="muted">—</span> : r.telegram ? "есть" : <span className="muted">нет</span>}</td>
                  {tour ? (
                    <td className="r">
                      {r.registered ? <span className="badge">записан</span>
                        : <button type="button" disabled={add.busy} onClick={() => enroll([r.user_id])}>В турнир</button>}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="hint">
        Гостей без аккаунта организатор привязывает к аккаунту игрока в списке участников турнира («Привязать аккаунт»).
        Новых игроков, которых ещё нет в клубе, записывайте по номеру игрока на странице турнира — они вступят в клуб автоматически.
      </p>
    </>
  );
}
