import Link from "next/link";
import { notFound } from "next/navigation";
import PlayerLookup from "@/components/PlayerLookup";
import { sget } from "@/lib/api";
import { plural } from "@/lib/format";

export async function generateMetadata({ params }: { params: Promise<{ no: string }> }) {
  const { no } = await params;
  return { title: `Игрок №${no}` };
}

const score = (avg: number | null, n: number) =>
  n ? `${avg!.toFixed(1).replace(".", ",")} из 5 (${n} ${plural(n, "оценка", "оценки", "оценок")})` : "оценок пока нет";

export default async function PlayerPage({ params }: { params: Promise<{ no: string }> }) {
  const { no } = await params;
  if (!/^\d{1,9}$/.test(no)) notFound();
  const p = await sget<any>(`/players/${no}`);
  if (!p) {
    return (
      <>
        <h1>Игрок №{no}</h1>
        <p>Игрока с таким номером нет. Проверьте номер: он есть в кабинете игрока и в боте по команде /id.</p>
        <PlayerLookup />
      </>
    );
  }
  const a = p.auction;
  return (
    <>
      <h1>{p.nickname}</h1>
      <p className="lead" style={{ marginTop: 0 }}>
        Номер игрока <b className="num">{p.player_no}</b> · на платформе с {new Date(p.since).toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}
        {p.banned ? <span className="badge" style={{ marginLeft: 8 }}>заблокирован на аукционе</span> : null}
      </p>
      <div className="split">
        <div>
          <h2 style={{ marginTop: 0 }}>Репутация на аукционе</h2>
          <dl className="facts">
            <dt>Как продавец</dt><dd>{score(a.seller_avg, a.seller_count)}</dd>
            <dt>Как покупатель</dt><dd>{score(a.buyer_avg, a.buyer_count)}</dd>
            <dt>Состоявшихся сделок</dt><dd>{a.deals_completed}</dd>
          </dl>
          {p.reviews.length ? (
            <>
              <h3>Отзывы</h3>
              <ul className="news-list">
                {p.reviews.map((r: any, i: number) => (
                  <li key={i} style={{ padding: "8px 0" }}>
                    <span className="num">{r.score}/5</span>{" "}
                    <span className="muted small">{r.role === "seller" ? "как продавцу" : "как покупателю"}</span>
                    <div>{r.comment}</div>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
        <aside className="stack">
          <div className="panel">
            <h3>Турниры</h3>
            <p style={{ margin: 0 }}>Сыграно турниров: {p.tournaments}</p>
            {p.clubs.length ? (
              <ul className="news-list" style={{ marginTop: 8 }}>
                {p.clubs.map((c: any) => (
                  <li key={c.slug} className="row" style={{ justifyContent: "space-between", padding: "6px 0" }}>
                    <Link href={`/clubs/${c.slug}`}>{c.name}</Link>
                    <span className="muted small">{c.events} {plural(c.events, "ивент", "ивента", "ивентов")}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          {p.judging.total || p.clubs.some((c: any) => c.judge.length) ? (
            <div className="panel">
              <h3>Судейство</h3>
              <p style={{ margin: 0 }}>Главный судья турниров: {p.judging.total}
                {p.judging.total ? <span className="muted"> ({Object.entries(p.judging.by_game).map(([g, n]) => `${g} ${n}`).join(", ")})</span> : null}</p>
              {p.clubs.filter((c: any) => c.judge.length).map((c: any) => (
                <p key={c.slug} className="small" style={{ margin: "6px 0 0" }}>Судья клуба <Link href={`/clubs/${c.slug}`}>{c.name}</Link>: {c.judge.join(", ")}</p>
              ))}
            </div>
          ) : null}
          <div className="panel"><PlayerLookup label="Другой игрок" /></div>
        </aside>
      </div>
    </>
  );
}
