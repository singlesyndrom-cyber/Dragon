import Link from "next/link";
import { notFound } from "next/navigation";
import Markdown from "@/components/Markdown";
import Standings from "@/components/Standings";
import { sget } from "@/lib/api";
import { dateOnly, dateTime, signed, T_STATUS } from "@/lib/format";

const STATUS: Record<string, string> = { active: "идёт", upcoming: "ещё не начался", finished: "завершён" };

export default async function League({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const l = await sget<any>(`/leagues/${id}`);
  if (!l) notFound();
  const edh = l.kind === "edh";
  const daysLeft = Math.ceil((new Date(l.ends_on).getTime() + 864e5 - Date.now()) / 864e5);
  return (
    <>
      <h1>{l.name}</h1>
      <p className="lead">
        <Link href={`/clubs/${l.club_slug}`}>{l.club}</Link>, {edh ? "EDH" : "Берсерк"}, {l.months}{" "}
        {l.months === 1 ? "месяц" : "месяца"}: {dateOnly(l.starts_on)} — {dateOnly(l.ends_on)}{dateOnly(l.ends_on).endsWith(".") ? "" : "."} Сезон {STATUS[l.status]}
        {l.status === "active" && daysLeft > 0 ? `, осталось ${daysLeft} дн.` : "."}
      </p>
      {l.description ? <Markdown text={l.description} /> : null}
      <div className="split">
        <section>
          <h2>{l.status === "finished" ? "Итоги сезона" : "Таблица сезона"}</h2>
          {edh ? (
            <Standings head={["Ивентов", "За сезон", "Банк"]} empty="Таблица заполнится после первого ивента сезона."
              rows={l.standings.map((r: any, i: number, all: any[]) => ({
                rank: all.findIndex((x: any) => Math.round(x.bank * 10) === Math.round(r.bank * 10)) + 1,   // равный банк — общее место
                name: r.nickname + (r.guest ? " (гость)" : ""), prize: i < 3 && r.delta > 0,
                cells: [r.events, signed(r.delta), Math.round(r.bank).toLocaleString("ru-RU")],
              }))} />
          ) : (
            <Standings head={["Турниров", "Победы", "Лучшее место", "Очки"]} empty="Таблица заполнится после первого турнира сезона."
              rows={l.standings.map((r: any, i: number, all: any[]) => ({
                rank: all.findIndex((x: any) => x.points === r.points && x.wins === r.wins) + 1, name: r.nickname,
                cells: [r.events, r.wins, r.best ?? "—", r.points],
              }))} />
          )}
          <p className="hint">
            {edh ? "Все начинают сезон с банком 1000. Каждую неделю пришедшие на ивент получают +150; победа за столом — 7% банка каждого соперника."
              : "Очки за матчи: победа 3, ничья 1, поражение 0, пропуск тура — 3. При равенстве выше тот, у кого больше побед."}
          </p>
        </section>
        <aside className="aside-block">
          <h3>Ивенты сезона</h3>
          {l.tournaments.length ? (
            <ul className="news-list">
              {l.tournaments.map((t: any) => (
                <li key={t.id} style={{ padding: "10px 0" }}>
                  <Link href={`/tournaments/${t.id}`}>{t.name}</Link>
                  <div className="muted small">{dateTime(t.starts_at)}, {T_STATUS[t.status].toLowerCase()}</div>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Ивентов пока нет.</p>}
        </aside>
      </div>
    </>
  );
}
