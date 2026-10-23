"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import EdhTables from "@/components/hub/EdhTables";
import Participants from "@/components/hub/Participants";
import SwissRounds from "@/components/hub/SwissRounds";
import Standings from "@/components/Standings";
import TournamentFields, { EMPTY, type Fields, toBody } from "@/components/TournamentFields";
import { api } from "@/lib/api";
import { dateTime, signed, T_STATUS } from "@/lib/format";
import { canRun, judgeDirection } from "@/lib/judges";
import { kindOf } from "@/lib/tournamentKinds";

type Tab = "players" | "rounds" | "standings" | "settings";

export default function ManageTournamentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Hub id={+id} /></Guard>;
}

function Hub({ id }: { id: number }) {
  const [t, setT] = useState<any>(null);
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [isOrg, setIsOrg] = useState(false);
  const [tab, setTab] = useState<Tab | null>(null);
  const load = useCallback(async () => {
    const tt = await api(`/tournaments/${id}`);
    setT(tt);
    const m = await api(`/clubs/${tt.club_id}/membership`).catch(() => null);
    setAllowed(canRun(m, tt));
    setIsOrg(!!m?.can_manage);
    // вкладка по умолчанию - по стадии турнира
    setTab((cur) => cur ?? (tt.status === "registration" ? "players" : tt.status === "running" ? "rounds" : "standings"));
  }, [id]);
  useEffect(() => { load().catch(() => setAllowed(false)); }, [load]);

  if (allowed === null) return <p className="muted">Загружаем…</p>;
  if (!allowed || !t) return <p>Вести турнир могут организаторы клуба и судьи клуба по этой игре.</p>;

  const edh = t.format === "edh";
  const kind = kindOf(t.game, t.format, t.draft);
  const tabs: [Tab, string][] = [
    ["players", `Участники (${t.participants.length})`],
    ["rounds", edh ? "Столы" : "Туры"],
    ["standings", "Таблица"],
    ...(t.status === "registration" && isOrg ? [["settings", "Настройки"] as [Tab, string]] : []),
  ];

  return (
    <>
      <div className="hub-head">
        <h1>{t.name}</h1>
        <p className="muted" style={{ margin: 0 }}>
          {kind?.title || t.format}, {T_STATUS[t.status].toLowerCase()}
          {t.round ? `, тур ${t.round}${t.rounds_total ? ` из ${t.rounds_total}` : ""}` : ""}.
          {" "}{dateTime(t.starts_at)}.
          {t.league ? <> Сезон: <Link href={`/leagues/${t.league.id}`}>{t.league.name}</Link>.</> : null}
        </p>
        <HeadJudge t={t} isOrg={isOrg} reload={load} />
        <p className="small" style={{ margin: "6px 0 0" }}>
          {t.draft ? <><Link href={`/manage/tournaments/${t.id}/draft`} className="btn primary small">Экран драфта и таймер туров</Link>{" "}</> : null}
          <Link href={`/tournaments/${t.id}`}>Публичная страница</Link>
          {t.self_registration && t.status === "registration" ? <span className="muted"> — ссылка для записи игроков</span> : null}
        </p>
      </div>

      <div className="tabs" role="tablist" aria-label="Разделы турнира">
        {tabs.map(([key, label]) => (
          <button key={key} role="tab" type="button" aria-selected={tab === key} className={tab === key ? "on" : undefined}
            onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === "players" ? <><Participants t={t} reload={load} /><DeckReview id={id} edh={edh} policy={t.deck_policy} /></> : null}
        {tab === "rounds" ? (edh ? <EdhTables t={t} reload={load} /> : <SwissRounds t={t} reload={load} />) : null}
        {tab === "standings" ? <StandingsTab t={t} /> : null}
        {tab === "settings" ? <SettingsTab t={t} reload={load} /> : null}
      </div>
      <DeleteTournament t={t} />
    </>
  );
}

/** Главный судья: виден всем ведущим турнир, назначает организатор (судьи клуба этого направления и организаторы). */
function HeadJudge({ t, isOrg, reload }: { t: any; isOrg: boolean; reload: () => Promise<void> }) {
  const [staff, setStaff] = useState<any[] | null>(null);
  const { busy, error, run } = useAction();
  const dir = judgeDirection(t.game, t.format);
  useEffect(() => {
    if (isOrg) api<any[]>(`/clubs/${t.club_id}/judges`).then((all) => setStaff(all.filter((s) => s.games.includes(dir)))).catch(() => setStaff([]));
  }, [isOrg, t.club_id, dir]);
  const label = t.judge ? `${t.judge.nickname}${t.judge.player_no ? ` (№${t.judge.player_no})` : ""}` : "не назначен";
  if (!isOrg || !staff) return <p className="small" style={{ margin: "6px 0 0" }}>Главный судья: {label}</p>;
  return (
    <div className="row inline" style={{ marginTop: 8 }}>
      <label style={{ margin: 0 }}>
        <span>Главный судья — попадёт в отчёт турнира</span>
        <select value={t.judge?.user_id ?? ""} disabled={busy}
          onChange={(e) => run(async () => {
            await api(`/tournaments/${t.id}/judge`, { method: "PUT", body: { user_id: e.target.value ? +e.target.value : null } });
            await reload();
          })}>
          <option value="">Не назначен</option>
          {staff.map((s) => <option key={s.user_id} value={s.user_id}>{s.nickname}{s.organizer ? " (организатор)" : ""}</option>)}
        </select>
      </label>
      <Status error={error} />
    </div>
  );
}

/** Удаление турнира: организатор клуба или судья клуба по этой игре, с подтверждением на странице. */
function DeleteTournament({ t }: { t: any }) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const edh = t.format === "edh";
  const effect = t.status === "registration"
    ? "Турнир и список участников будут удалены."
    : edh
      ? "Турнир, столы и результаты будут удалены, изменения банков EDH по этому ивенту откатятся."
      : "Турнир, туры и результаты будут удалены, очки лиги клуба за него откатятся.";
  return (
    <section className="danger-zone">
      <h3>Удаление турнира</h3>
      <p className="hint">
        {effect} Гости, которые больше нигде не играли, тоже удалятся. Сообщения, уже отправленные ботом в Telegram,
        останутся в чате. Отменить удаление нельзя.
      </p>
      <ConfirmButton className="danger" danger disabled={busy}
        question={`Удалить турнир «${t.name}» безвозвратно?`} confirmLabel="Да, удалить"
        onConfirm={() => run(async () => {
          await api(`/tournaments/${t.id}`, { method: "DELETE" });
          router.replace(t.club_slug ? `/clubs/${t.club_slug}` : "/tournaments");
        })}>
        Удалить турнир
      </ConfirmButton>
      <Status error={error} />
    </section>
  );
}

/** Журнал исправлений результатов (швейцарка): кто и когда поменял уже введённый результат. */
function EditLog({ t }: { t: any }) {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { api<any[]>(`/tournaments/${t.id}/edits`).then(setRows).catch(() => {}); }, [t.id, t.round, t.status]);
  if (!rows.length) return null;
  const word = (r: string, a: any) => (r === "draw" ? "ничья" : `победа ${r === "p1" ? a.p1 : a.p2}`);
  return (
    <section>
      <h3>Исправления результатов</h3>
      <ul className="news-list small">
        {rows.map((r, i) => (
          <li key={i} style={{ padding: "6px 0" }}>
            {dateTime(r.at)} · тур {r.round} · {r.p1} — {r.p2}: {word(r.before, r)} → <b>{word(r.after, r)}</b>
            <span className="muted"> · исправил {r.by || "—"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StandingsTab({ t }: { t: any }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    setRows(null);
    if (t.format === "edh") api<any[]>(`/edh/${t.id}/results`).then(setRows).catch(() => setRows([]));
    else if (t.round) api<any[]>(`/tournaments/${t.id}/standings`).then(setRows).catch(() => setRows([]));
    else setRows([]);
  }, [t.id, t.format, t.round, t.status]);
  if (rows === null) return <p className="muted">Загружаем…</p>;
  if (t.format === "edh") {
    return (
      <Standings head={["Партий", "Изменение банка", "Банк"]} empty="Результатов пока нет: закройте хотя бы один стол."
        rows={rows.map((r, i, all) => ({
          rank: all.findIndex((x) => Math.round(x.net * 10) === Math.round(r.net * 10)) + 1, name: r.nickname,
          prize: r.net > 0 && i < 3,
          cells: [r.games, signed(r.net), r.bank != null ? Math.round(r.bank).toLocaleString("ru-RU") : "—"],
        }))} />
    );
  }
  return (
    <>
      <Standings head={["Очки", "Победы", "OWP", "Buchholz"]} empty="Таблица появится после первого тура."
        rows={rows.map((r) => ({
          rank: r.rank, name: r.player + (r.dropped && t.status !== "registration" ? " (выбыл)" : ""),
          cells: [r.points, r.wins, (r.owp * 100).toFixed(1) + "%", r.buchholz],
        }))} />
      <p className="hint">При равных очках выше тот, у кого выше OWP (процент побед соперников), затем Buchholz, затем очки лиги клуба.</p>
      <EditLog t={t} />
    </>
  );
}

function SettingsTab({ t, reload }: { t: any; reload: () => Promise<void> }) {
  const [f, setF] = useState<Fields>(EMPTY);
  const [seasons, setSeasons] = useState<any[] | null>(null);
  const { busy, error, done, run } = useAction();
  const kind = kindOf(t.game, t.format, t.draft);
  useEffect(() => {
    const local = t.starts_at ? new Date(t.starts_at) : null;
    const pad = (n: number) => String(n).padStart(2, "0");
    setF({
      name: t.name, description: t.description || "", rounds: t.rounds_total ? String(t.rounds_total) : "",
      deck_policy: t.deck_policy, self_registration: t.self_registration, silent: !!t.silent, tier: t.tier || "club", max_players: t.max_players ? String(t.max_players) : "",
      league_id: t.league_id ? String(t.league_id) : "",
      starts_at: local ? `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}T${pad(local.getHours())}:${pad(local.getMinutes())}` : "",
    });
    if (kind?.league) {
      api<any[]>(`/leagues?club_id=${t.club_id}`)
        .then((all) => setSeasons(all.filter((s) => s.kind === kind.league && (s.status !== "finished" || s.id === t.league_id))))
        .catch(() => setSeasons([]));
    }
  }, [t, kind?.league]);
  return (
    <form className="wizard" onSubmit={(e) => {
      e.preventDefault();
      run(async () => { await api(`/tournaments/${t.id}`, { method: "PATCH", body: toBody(f, t.format) }); await reload(); }, "Настройки сохранены");
    }}>
      <TournamentFields f={f} set={(p) => setF((cur) => ({ ...cur, ...p }))} format={t.format} seasons={kind?.league ? seasons : null} />
      <button className="primary" disabled={busy}>Сохранить настройки</button>
      <Status error={error} done={done} />
      <p className="hint">После старта настройки меняются только у участников и результатов.</p>
    </form>
  );
}

function DeckReview({ id, edh, policy }: { id: number; edh: boolean; policy: string }) {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { if (policy !== "none") api<any[]>(`/decks/tournament/${id}`).then(setRows).catch(() => {}); }, [id, policy]);
  if (policy === "none" || !rows.some((r) => r.deck_id)) return null;
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

