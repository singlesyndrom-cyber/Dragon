import Link from "next/link";
import { notFound } from "next/navigation";
import { sget } from "@/lib/api";
import { CONDITIONS, dateTime, rub } from "@/lib/format";

const BOT = process.env.NEXT_PUBLIC_TG_BOT_NAME;
const STATUS: Record<string, string> = { active: "Идут торги", sold: "Продано", unsold: "Без ставок", cancelled: "Снят с торгов" };

export default async function Lot({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const l = await sget<any>(`/auctions/lots/${id}`);
  if (!l) notFound();
  return (
    <>
      <h1>{l.title}</h1>
      <div className="split">
        <div>
          <dl className="facts">
            <dt>Статус</dt><dd>{STATUS[l.status]}</dd>
            <dt>Состояние</dt><dd>{l.condition}, {CONDITIONS[l.condition]}</dd>
            <dt>Продавец</dt>
            <dd>
              {l.seller_no ? <Link href={`/players/${l.seller_no}`}>{l.seller} <span className="muted small">№{l.seller_no}</span></Link> : l.seller}{" "}
              <span className="muted">
                {l.seller_count ? `рейтинг ${l.seller_avg.toFixed(1).replace(".", ",")} из 5 по ${l.seller_count} оценкам` : "новый продавец"}
              </span>
            </dd>
            <dt>Старт</dt><dd className="num">{rub(l.start_price)}</dd>
            <dt>{l.status === "sold" ? "Итоговая цена" : "Текущая ставка"}</dt>
            <dd className="num gold">{l.current_price ? rub(l.current_price) : "ставок пока нет"}</dd>
            {l.status === "active" ? (<><dt>Следующая ставка</dt><dd className="num">от {rub(l.next_bid)}</dd>
              <dt>Окончание</dt><dd>{dateTime(l.ends_at)}</dd></>) : null}
          </dl>
          {l.status === "active" ? (
            <div className="row section">
              {l.post_url ? <a className="btn primary" href={l.post_url}>Открыть лот в Telegram</a> : null}
              {BOT ? <a className="btn" href={`https://t.me/${BOT}?start=bid_${l.id}`}>Сделать свою ставку</a> : null}
            </div>
          ) : null}
          <h2>История ставок</h2>
          {l.bids_history.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Участник</th><th className="r">Ставка</th><th>Время</th></tr></thead>
                <tbody>
                  {l.bids_history.map((b: any, i: number) => (
                    <tr key={i}>
                      <td>{b.nickname}</td>
                      <td className="r">{rub(b.amount)}</td>
                      <td className="muted">{dateTime(b.at)}{b.extended ? ", торги продлены" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="muted">Ставок пока нет.</p>}
        </div>
        <aside>
          {l.photo_url ? <img src={`/api${l.photo_url}`} alt={l.title} style={{ width: "100%", borderRadius: 12 }} /> : null}
        </aside>
      </div>
    </>
  );
}
