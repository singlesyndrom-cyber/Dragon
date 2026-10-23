"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { searchHref } from "@/lib/cards";
import { plural } from "@/lib/format";
import { dayLabel, fill, formatLabel, seatsLabel, timeOf, type HomeEvent, type HomeGame } from "@/lib/home";

type Season = { name: string; club: string; place: number; value: number; events: number; gap: number | null; kind: string };
type OrgClub = { id: number; name: string; slug: string; today: HomeEvent[]; today_players: number; week: number;
  missing_decks: number; bookings_today: number };
type MeData = { tournaments: HomeEvent[]; decks: { id: number; name: string; cards: number }[]; decks_total: number;
  season: Season | null; organizer: OrgClub[] };

const GAME_NAME: Record<HomeGame, string> = { mtg: "Magic: The Gathering", berserk: "«Берсерк»" };

function CardSearch({ game }: { game: HomeGame }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) router.push(searchHref(q.trim(), game)); };
  return (
    <form onSubmit={submit} className="cardsearch big h-search" role="search">
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Поиск карты"
        placeholder={game === "mtg" ? "Карта MTG: название по-русски или по-английски" : "Карта «Берсерка»: название, стихия, класс"} />
      <button type="submit">Найти карту</button>
    </form>
  );
}

function greeting(now: Date): string {
  const h = Number(now.toLocaleString("en-GB", { timeZone: "Europe/Moscow", hour: "2-digit", hour12: false }));
  return h < 5 ? "Доброй ночи" : h < 12 ? "Доброе утро" : h < 18 ? "Добрый день" : "Добрый вечер";
}

function Guest({ game, next, now }: { game: HomeGame; next: HomeEvent | null; now: string }) {
  const f = next ? fill(next) : null;
  return (
    <>
      <section className="h-hero">
        <div className="h-hero-text">
          <span className="h-kicker">Клубная платформа · {GAME_NAME[game]}</span>
          <h1>Турниры, колоды и мета вашего клуба — в одном месте</h1>
          <p className="lead">Запишитесь на турнир, подайте колоду, следите за парингами и результатами в реальном времени.
            Организаторам — регистрация, паринги, таймеры и драфт без таблиц и бумажек.</p>
          <CardSearch game={game} />
          <div className="row">
            <Link href="/tournaments" className="btn primary big">Найти турнир</Link>
            <Link href="/clubs/new" className="btn big">Открыть свой клуб</Link>
          </div>
        </div>
        {next ? (
          <div className="h-card h-next">
            <div className="h-next-top">
              <span className="h-label">Ближайший турнир</span>
              <span className={next.status === "running" ? "h-live" : "badge"}>
                {next.status === "running" ? "идёт сейчас" : `${dayLabel(next.starts_at, now)}, ${timeOf(next.starts_at)}`}
              </span>
            </div>
            <h2>{next.name}</h2>
            <p className="muted">клуб «{next.club}»</p>
            <div className="row small"><span className="badge">{formatLabel(next)}</span><span className="badge">{seatsLabel(next)}</span></div>
            {f !== null ? <div className="h-bar" aria-hidden="true"><span style={{ width: `${f}%` }} /></div> : null}
            <Link href={`/tournaments/${next.id}`} className="btn big">{next.status === "running" ? "Смотреть" : "Записаться"}</Link>
          </div>
        ) : null}
      </section>
      <section aria-labelledby="how">
        <h2 id="how">Как это работает</h2>
        <ol className="h-steps">
          <li><span className="h-step">1</span><div><b>Найдите клуб</b><p className="muted small">Клубы рядом, их игры и ближайшие турниры — на одной странице.</p><Link href="/clubs">Все клубы →</Link></div></li>
          <li><span className="h-step">2</span><div><b>Запишитесь на турнир</b><p className="muted small">Регистрация за минуту, подача колоды онлайн, напоминание в Telegram.</p><Link href="/tournaments">Расписание →</Link></div></li>
          <li><span className="h-step">3</span><div><b>Играйте и следите за результатами</b><p className="muted small">Паринги, столы и очки в реальном времени; рейтинг сезона и мета клуба.</p><Link href={`/meta?game=${game}`}>Мета →</Link></div></li>
        </ol>
      </section>
    </>
  );
}

function Organizer({ club, now }: { club: OrgClub; now: string }) {
  const tiles: [string, number, string][] = [
    ["На турнирах сегодня", club.today_players, `${club.today.length} ${plural(club.today.length, "турнир", "турнира", "турниров")}`],
    ["Турниров на неделе", club.week, "открыта регистрация или идут"],
    ["Колоды не поданы", club.missing_decks, "где деклист обязателен"],
    ["Брони столов сегодня", club.bookings_today, "активные брони"],
  ];
  return (
    <section className="h-org">
      <div className="h-head">
        <div><span className="h-kicker">Ваш клуб сегодня</span><h1>«{club.name}»</h1></div>
        <div className="row">
          <Link href={`/tournaments/new?club=${club.id}`} className="btn primary big">Создать турнир</Link>
          <Link href={`/manage/clubs/${club.id}`} className="btn big">Управление клубом</Link>
        </div>
      </div>
      <div className="h-tiles">
        {tiles.map(([l, v, s]) => (
          <div key={l} className="h-card"><span className="muted small">{l}</span><b className="h-big num">{v}</b><span className="muted small">{s}</span></div>
        ))}
      </div>
      {club.today.length ? (
        <ul className="h-card h-todo">
          {club.today.map((t) => (
            <li key={t.id}>
              <span className="num"><b>{timeOf(t.starts_at)}</b></span>
              <span className="h-grow">{t.name} — {t.status === "running" ? (t.round ? `идёт тур ${t.round}${t.rounds_total ? ` из ${t.rounds_total}` : ""}` : "идёт") : seatsLabel(t)}
                <span className="muted small"> · {formatLabel(t)}</span></span>
              {t.draft ? <Link href={`/manage/tournaments/${t.id}/draft`}>Экран драфта</Link> : null}
              <Link href={`/manage/tournaments/${t.id}`} className="btn">Вести турнир</Link>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Сегодня турниров нет. Ближайшие — в расписании ниже.</p>}
    </section>
  );
}

function Player({ data, game, nick, now }: { data: MeData; game: HomeGame; nick: string; now: string }) {
  const s = data.season;
  return (
    <section className="h-player">
      <div className="h-head">
        <h1>{greeting(new Date(now))}, {nick}</h1>
        <CardSearch game={game} />
      </div>
      <div className="h-player-grid">
        <div className="h-card">
          <h2 className="h-label">Ваши ближайшие турниры</h2>
          {data.tournaments.length ? (
            <ul className="h-mine">
              {data.tournaments.map((t) => {
                const needDeck = t.status === "registration" && !t.draft && t.deck_policy !== "none" && !t.deck_id;
                return (
                  <li key={t.id}>
                    <span className="h-when num"><span className="muted small">{t.status === "running" ? "Сейчас" : dayLabel(t.starts_at, now)}</span><b>{timeOf(t.starts_at)}</b></span>
                    <span className="h-grow"><Link href={`/tournaments/${t.id}`}><b>{t.name}</b></Link><br /><span className="muted small">{formatLabel(t)} · «{t.club}»</span></span>
                    {needDeck ? <Link href={`/tournaments/${t.id}`} className="btn primary">Подать колоду</Link>
                      : t.deck_name ? <span className="win small">Колода: {t.deck_name}</span>
                      : t.draft ? <span className="muted small">Колода собирается на драфте</span> : null}
                  </li>
                );
              })}
            </ul>
          ) : <p className="muted">Вы пока никуда не записаны. <Link href="/tournaments">Найти турнир →</Link></p>}
        </div>
        <div className="h-card">
          {s ? (
            <>
              <h2 className="h-label">{s.name} · «{s.club}»</h2>
              <p className="h-place"><b className="gold">{s.place}</b> <span className="muted">место · {s.value} {s.kind === "edh" ? "банк" : plural(Math.round(s.value), "очко", "очка", "очков")}</span></p>
              {s.gap ? <p className="muted small">До места выше — {s.gap}.</p> : s.place === 1 ? <p className="muted small">Вы лидер сезона.</p> : null}
            </>
          ) : null}
          <h2 className="h-label">Мои колоды{data.decks_total ? ` · ${data.decks_total}` : ""}</h2>
          {data.decks.length ? (
            <ul className="h-decks">
              {data.decks.map((d) => <li key={d.id}><Link href={`/decks/${d.id}`}>{d.name}</Link><span className="muted small num">{d.cards} карт</span></li>)}
            </ul>
          ) : <p className="muted small">Колод этой игры пока нет.</p>}
          <Link href={`/decks/new?game=${game}`}>+ Собрать колоду</Link>
        </div>
      </div>
    </section>
  );
}

/** Первый экран главной: гость, игрок или организатор. */
export default function HomeHero({ game, next, now }: { game: HomeGame; next: HomeEvent | null; now: string }) {
  const { me, ready } = useAuth();
  const [data, setData] = useState<MeData | null>(null);
  useEffect(() => {
    if (!me) { setData(null); return; }
    let live = true;
    api<MeData>(`/home/me?game=${game}`).then((d) => { if (live) setData(d); }).catch(() => { if (live) setData(null); });
    return () => { live = false; };
  }, [me, game]);

  if (!ready || (me && !data)) return <div className="h-skeleton" aria-busy="true" />;
  if (!me || !data) return <Guest game={game} next={next} now={now} />;
  const org = data.organizer[0];
  return (
    <>
      {org ? <Organizer club={org} now={now} /> : null}
      {!org || data.tournaments.length ? <Player data={data} game={game} nick={me.nickname} now={now} /> : null}
    </>
  );
}
