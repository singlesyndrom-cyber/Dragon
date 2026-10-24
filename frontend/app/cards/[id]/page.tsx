import Link from "next/link";
import { notFound } from "next/navigation";
import CardPrints from "@/components/CardPrints";
import Mana from "@/components/Mana";
import WotcNotice from "@/components/WotcNotice";
import { sget } from "@/lib/api";
import { BK_CREDIT, BK_ICON_RU, Bk, bkIconUrl } from "@/lib/berserk";
import { qv, searchHref } from "@/lib/cards";
import { RS_CREDIT, type Rs } from "@/lib/response";

const FORMATS: [string, string][] = [
  ["commander", "Commander (EDH)"], ["standard", "Standard"], ["pioneer", "Pioneer"], ["modern", "Modern"],
  ["legacy", "Legacy"], ["vintage", "Vintage"], ["pauper", "Pauper"], ["duel", "Duel Commander"], ["brawl", "Brawl"],
];
const LEGAL: Record<string, [string, string]> = {
  legal: ["разрешена", "win"], not_legal: ["нет", "muted"], banned: ["запрещена", "loss"], restricted: ["ограничена", "gold"],
};

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

  const typeQuery = (c.type || "").split(" — ")[0].split(/\s+/).filter(Boolean).map((w: string) => `t:${w}`).join(" ");
  return (
    <>
      <p className="muted small"><Link href={`/cards?game=${c.game}`}>← Картотека</Link></p>
      <h1>{c.name_ru || c.name}</h1>
      {c.name_ru ? <p className="lead" style={{ marginTop: "-0.4em" }}>{c.name}</p> : null}
      <div className="split">
        <div>
          {c.rs ? <ResponsePanel c={c} /> : c.bk ? <BerserkPanel c={c} /> : faces.length ? faces.map((f, i) => (
            <section key={i} className="panel">
              <h3><Mana text={f.mana_cost} /> {f.name}</h3>
              <p className="muted">{f.type_line}</p>
              <OracleText text={f.text} />
            </section>
          )) : (
            <section className="panel">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <Link href={searchHref(typeQuery, c.game)} className="muted">{c.type}</Link>
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
          <CardPrints card={c} backFallback={faces[1]?.image && faces[1].image !== faces[0]?.image ? faces[1].image : null} />
          {c.scryfall_uri ? (
            <a href={c.scryfall_uri} className="small" target="_blank" rel="noopener">
              {c.game === "berserk" ? "Карта на ProBerserk.ru" : "Карта на Scryfall"}</a>
          ) : null}
        </aside>
      </div>
      {c.game === "mtg" ? <WotcNotice /> : null}
      {c.game === "berserk" ? <p className="muted small section">{BK_CREDIT}</p> : null}
      {c.game === "response" ? <p className="muted small section">{RS_CREDIT}</p> : null}
    </>
  );
}

/** Карта «Берсерка»: стоимость (элитная/рядовая), стихия, класс, здоровье, движение, удар, значки и текст. */
function BerserkPanel({ c }: { c: any }) {
  const b: Bk = c.bk || {};
  const icons = Object.entries(b.icons || {});
  return (
    <section className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted">
          <Link href={searchHref(`t:${qv(b.kind || "")}`, "berserk")} className="muted">{b.kind}</Link>
          {b.class ? <> · <Link href={searchHref(`класс:${qv(b.class)}`, "berserk")} className="muted">{b.class}</Link></> : null}
        </span>
        <span className="gold" title={b.elite ? "Элитная" : "Рядовая"}>
          {c.mana_cost} <img src={bkIconUrl(b.elite ? "elite" : "ordinary")} alt={b.elite ? "Элитная" : "Рядовая"} height={18}
            style={{ verticalAlign: "-0.2em" }} />
        </span>
      </div>
      <dl className="facts small" style={{ marginTop: 10 }}>
        <dt>Стихия</dt>
        <dd>{(b.elements || []).map((el, i) => (
          <span key={el}>{i ? ", " : ""}<Link href={searchHref(`el:${el.toLowerCase()}`, "berserk")}>{el}</Link></span>
        ))}</dd>
        <dt>Стоимость</dt><dd>{c.mana_cost} · {b.elite ? "элитная" : "рядовая"}{b.unique ? " · уникальная" : ""}</dd>
        {b.health != null ? <><dt>Жизни</dt><dd className="num">{b.health}</dd></> : null}
        {b.move != null ? <><dt>Движение</dt><dd className="num">{b.move}</dd></> : null}
        {b.strike ? <><dt>Удар</dt><dd className="num">{b.strike}</dd></> : null}
        {icons.length ? (
          <><dt>Значки</dt><dd>{icons.map(([k, v]) => (
            <span key={k} title={BK_ICON_RU[k] || k} style={{ marginRight: 8 }}>
              <img src={bkIconUrl(k)} alt={BK_ICON_RU[k] || k} height={18} style={{ verticalAlign: "-0.25em" }} />{v === true ? "" : v}
            </span>
          ))}</dd></>
        ) : null}
        {b.number ? <><dt>Номер</dt><dd className="num">{b.number}</dd></> : null}
      </dl>
      <div style={{ marginTop: 12 }}><OracleText text={c.text} /></div>
    </section>
  );
}

/** Карта «Респонса»: тип, стоимость (влияние), фракции, сила/прочность, уровни героя, разъяснения, издания. */
function ResponsePanel({ c }: { c: any }) {
  const r: Rs = c.rs || {};
  const types = [...(r.supertypes || []), ...(r.types || [])];
  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="muted">
            {types.map((t, i) => <span key={t}>{i ? " " : ""}<Link href={searchHref(`t:${qv(t)}`, "response")} className="muted">{t}</Link></span>)}
            {r.subtypes?.length ? <> — {r.subtypes.join(", ")}</> : null}
          </span>
          {c.mana_cost != null ? <span className="gold" title="Стоимость (влияние)">♛ {c.mana_cost}</span> : null}
        </div>
        <dl className="facts small" style={{ marginTop: 10 }}>
          <dt>Фракции</dt>
          <dd>{(r.factions || []).map((f, i) => (
            <span key={f}>{i ? ", " : ""}<Link href={searchHref(`фракция:${f.toLowerCase()}`, "response")}>{f}</Link></span>
          ))}</dd>
          {r.strength != null ? <><dt>Сила</dt><dd className="num">{r.strength}</dd></> : null}
          {r.durability != null ? <><dt>Прочность</dt><dd className="num">{r.durability}</dd></> : null}
          {c.rarity ? <><dt>Редкость</dt><dd>{c.rarity}</dd></> : null}
          {r.legendary ? <><dt>Ограничение</dt><dd>легендарная — одна копия в колоде</dd></> : null}
        </dl>
        {r.hero && r.levels?.length ? (
          <div style={{ marginTop: 12 }}>
            {r.levels.map((lv, i) => (
              <p key={i} style={{ margin: "0 0 0.6em" }}><b>Уровень {i + 1}</b> <span className="muted">· влияние {lv.influence ?? "—"}</span><br />{lv.text}</p>
            ))}
          </div>
        ) : <div style={{ marginTop: 12 }}><OracleText text={c.text} /></div>}
      </section>
      {r.rulings?.length ? (
        <section className="panel">
          <h3>Разъяснения</h3>
          <ul style={{ margin: 0, paddingLeft: 18 }}>{r.rulings.map((t) => <li key={t} style={{ marginBottom: 6 }}>{t}</li>)}</ul>
        </section>
      ) : null}
      {r.printings?.length ? (
        <p className="muted small">Издания: {r.printings.map((p) => `${p.set} №${p.number} (${p.rarity})`).join("; ")}</p>
      ) : null}
    </>
  );
}
