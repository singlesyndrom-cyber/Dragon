import Link from "next/link";
import { sget } from "@/lib/api";
import { dateTime, rub } from "@/lib/format";

export const metadata = { title: "Аукцион" };

const BOT = process.env.NEXT_PUBLIC_TG_BOT_NAME;

export default async function Auctions({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status = "active" } = await searchParams;
  const lots = (await sget<any[]>(`/auctions/lots?status=${status === "sold" ? "sold" : "active"}&limit=60`)) || [];
  return (
    <>
      <h1>Аукцион карт</h1>
      <p className="lead">
        Лоты выставляются и разыгрываются в Telegram: бот публикует карту в торговом канале, ставки делаются кнопкой
        под постом. Ставка в последние 5 минут продлевает торги ещё на 5 минут.
        {BOT ? <> Выставить карту: <a href={`https://t.me/${BOT}`}>@{BOT}</a>, команда /sell.</> : null}
      </p>
      <div className="row">
        <Link href="/auctions" className={status !== "sold" ? "btn primary" : "btn"}>Идут торги</Link>
        <Link href="/auctions?status=sold" className={status === "sold" ? "btn primary" : "btn"}>Проданные</Link>
      </div>
      {lots.length ? (
        <div className="grid section">
          {lots.map((l) => (
            <Link key={l.id} href={`/auctions/${l.id}`} className="tile">
              {l.photo_url ? <img src={`/api${l.photo_url}`} alt="" loading="lazy" /> : <span className="noimg">{l.title}</span>}
              <span className="cap">
                <b>{l.title}</b>
                <span className="num gold">{rub(l.current_price ?? l.start_price)}</span>
                <span className="muted small"> {l.condition}</span>
                <br />
                <span className="muted small">
                  {l.status === "active" ? `до ${dateTime(l.ends_at)}` : `ставок: ${l.bids}`}
                </span>
              </span>
            </Link>
          ))}
        </div>
      ) : <p className="muted section">{status === "sold" ? "Проданных лотов пока нет." : "Сейчас нет активных лотов."}</p>}
    </>
  );
}
