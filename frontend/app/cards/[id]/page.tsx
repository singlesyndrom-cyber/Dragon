import { notFound } from "next/navigation";
import Mana from "@/components/Mana";
import WotcNotice from "@/components/WotcNotice";
import { sget } from "@/lib/api";

const FORMATS: [string, string][] = [
  ["commander", "Commander (EDH)"], ["standard", "Standard"], ["pioneer", "Pioneer"], ["modern", "Modern"],
  ["legacy", "Legacy"], ["vintage", "Vintage"], ["pauper", "Pauper"], ["duel", "Duel Commander"], ["brawl", "Brawl"],
];
const LEGAL: Record<string, [string, string]> = {
  legal: ["разрешена", "win"], not_legal: ["нет", "muted"], banned: ["запрещена", "loss"], restricted: ["ограничена", "gold"],
};
const RARITY: Record<string, string> = { common: "обычная", uncommon: "необычная", rare: "редкая", mythic: "мифическая", special: "особая", bonus: "бонусная" };

function OracleText({ text }: { text?: string | null }) {
  if (!text) return null;
  return <>{text.split("\n").map((line, i) => <p key={i} style={{ margin: "0 0 0.6em" }}><Mana text={line} /></p>)}</>;
}

export default async function CardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const c = await sget<any>(`/cards/${id}`);
  if (!c) notFound();
  const x = c.extra || {};
  const faces: any[] = x.faces || [];
  const pt = x.power != null ? `${x.power}/${x.toughness}` : x.loyalty ? `верность ${x.loyalty}` : null;
  const prices = c.prices || {};

  return (
    <>
      <h1>{c.name_ru || c.name}</h1>
      {c.name_ru ? <p className="lead" style={{ marginTop: "-0.4em" }}>{c.name}</p> : null}
      <div className="split">
        <div>
          {faces.length ? faces.map((f, i) => (
            <section key={i} className="panel">
              <h3><Mana text={f.mana_cost} /> {f.name}</h3>
              <p className="muted">{f.type_line}</p>
              <OracleText text={f.text} />
            </section>
          )) : (
            <section className="panel">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="muted">{c.type}</span>
                <span><Mana text={c.mana_cost} size={18} /></span>
              </div>
              <div style={{ marginTop: 12 }}><OracleText text={c.text} /></div>
              {pt ? <p className="gold" style={{ textAlign: "right", margin: 0 }}>{pt}</p> : null}
            </section>
          )}

          {c.text_ru ? (
            <section className="panel">
              <h3>Русский текст</h3>
              {c.type_ru ? <p className="muted">{c.type_ru}</p> : null}
              <OracleText text={c.text_ru} />
              <p className="muted small" style={{ margin: 0 }}>Текст русской печати; официальные правила — английский Oracle-текст выше.</p>
            </section>
          ) : null}

          {c.game === "mtg" && Object.keys(c.legalities || {}).length ? (
            <>
              <h2>Форматы</h2>
              <div className="table-wrap">
                <table>
                  <tbody>
                    {FORMATS.filter(([k]) => k in c.legalities).map(([k, label]) => {
                      const [txt, cls] = LEGAL[c.legalities[k]] || [c.legalities[k], "muted"];
                      return <tr key={k}><td>{label}</td><td className={cls}>{txt}</td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
              {c.is_game_changer ? <p className="small">Входит в список Game Changers: влияет на выбор брекета в EDH.</p> : null}
            </>
          ) : null}
        </div>
        <aside className="stack">
          {c.image_url ? (
            <a href={x.image_large || c.image_url}><img src={c.image_url} alt={c.name} style={{ width: "100%", borderRadius: 14 }} /></a>
          ) : null}
          {faces[1]?.image ? <img src={faces[1].image} alt={faces[1].name} style={{ width: "100%", borderRadius: 14 }} /> : null}
          <dl className="facts">
            {c.set_name ? (<><dt>Сет</dt><dd>{c.set_name}</dd></>) : null}
            {c.rarity ? (<><dt>Редкость</dt><dd>{RARITY[c.rarity] || c.rarity}</dd></>) : null}
            {x.artist ? (<><dt>Художник</dt><dd>{x.artist}</dd></>) : null}
            {prices.usd || prices.eur ? (
              <><dt>Цена</dt><dd className="num">{[prices.usd && `$${prices.usd}`, prices.eur && `€${prices.eur}`].filter(Boolean).join(", ")}
                {prices.usd_foil ? <span className="muted"> (фойл ${prices.usd_foil})</span> : null}</dd></>
            ) : null}
          </dl>
          {c.scryfall_uri ? <a href={c.scryfall_uri} className="small">Карта на Scryfall</a> : null}
        </aside>
      </div>
      {c.game === "mtg" ? <WotcNotice /> : null}
    </>
  );
}
