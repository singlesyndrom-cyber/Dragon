"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useRef, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import DeckFileInput from "@/components/deck/DeckFileInput";
import DeckList, { Ops } from "@/components/deck/DeckList";
import DeckStats from "@/components/deck/DeckStats";
import PrintPicker from "@/components/deck/PrintPicker";
import Problems from "@/components/deck/Problems";
import { useLang } from "@/components/deck/useLang";
import { Status, useAction } from "@/components/Form";
import FlipCard from "@/components/FlipCard";
import Guard from "@/components/Guard";
import Mana from "@/components/Mana";
import { api } from "@/lib/api";
import { bkCost } from "@/lib/berserk";
import { BK_FORMATS, COMMANDER_FORMATS, CardInfo, DECK_FORMATS, Row, VISIBILITY, count, fromApi, playing } from "@/lib/decks";

export default function EditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Editor id={id} /></Guard>;
}

type Save = "saved" | "dirty" | "saving" | "error";
let seq = 0;
const newKey = () => `n${Date.now()}-${seq++}`;

function Editor({ id }: { id: string }) {
  const router = useRouter();
  const [d, setD] = useState<any>(undefined);
  const [rows, setRows] = useState<Row[]>([]);
  const [problems, setProblems] = useState<any[]>([]);
  const [save, setSave] = useState<Save>("saved");
  const [saveErr, setSaveErr] = useState("");
  const [preview, setPreview] = useState<{ name: string; image?: string | null; back?: string | null } | null>(null);
  const [lang, setLang] = useLang();
  const [importing, setImporting] = useState(false);
  const [printKey, setPrintKey] = useState<string | null>(null);
  const loaded = useRef(false);
  const version = useRef(0);
  const { busy, error, run } = useAction();

  async function load() {
    const x = await api<any>(`/decks/${id}`);
    setD(x);
    const rs = fromApi(x.cards);
    setRows(rs);
    setProblems(x.problems);
    const first = rs.find((r) => r.section === "commander" && r.card) || rs.find((r) => r.card);
    if (first) setPreview({ name: first.name, image: first.card?.image_url, back: first.card?.back_image });
    loaded.current = false;
  }
  useEffect(() => { load().catch(() => setD(null)); }, [id]);

  // автосохранение списка карт: через 0,7 с после последнего изменения
  useEffect(() => {
    if (!d) return;
    if (!loaded.current) { loaded.current = true; return; }
    setSave("dirty");
    const v = ++version.current;
    const h = setTimeout(async () => {
      setSave("saving");
      try {
        const r = await api<any>(`/decks/${id}/cards`, { method: "PUT", body: {
          cards: rows.map((x) => ({ card_id: x.card?.id ?? null, name: x.card ? null : x.name, qty: x.qty, section: x.section,
            print_id: x.card?.print?.id ?? null })) } });
        if (v === version.current) { setProblems(r.problems); setSave("saved"); setSaveErr(""); }
      } catch (e: any) {
        if (v === version.current) { setSave("error"); setSaveErr(e.message); }
      }
    }, 700);
    return () => clearTimeout(h);
  }, [rows]);

  // предупредить о несохранённых изменениях при уходе со страницы
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (save === "dirty" || save === "saving") e.preventDefault(); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [save]);

  if (d === undefined) return <p className="muted">Загружаем…</p>;
  if (!d || !d.editable) return <p>Колода не найдена. Редактировать можно только свои колоды.</p>;
  if (d.locked) {
    return <p>Колода подана на начавшийся турнир — изменить её можно после окончания. <Link href={`/decks/${id}`}>Открыть колоду</Link></p>;
  }

  const isCmd = COMMANDER_FORMATS.has(d.format);
  const bk = d.game === "berserk";
  const formats = bk ? BK_FORMATS : DECK_FORMATS;

  function add(card: CardInfo, section: Row["section"], qty = 1) {
    setRows((prev) => {
      let next = prev;
      if (section === "commander") next = next.filter((r) => !(r.card?.id === card.id && r.section === "main"));
      const i = next.findIndex((r) => r.card?.id === card.id && r.section === section);
      if (i >= 0) return next.map((r, j) => j === i ? { ...r, qty: section === "commander" ? 1 : r.qty + qty } : r);
      return [...next, { key: newKey(), name: card.name, qty: section === "commander" ? 1 : qty, section, card }];
    });
    setPreview({ name: card.name, image: card.image_url, back: card.back_image });
  }
  const ops: Ops = {
    print: bk ? undefined : (key) => setPrintKey(key),        // издания есть только у карт MTG
    qty: (key, delta) => setRows((prev) => prev.flatMap((r) => r.key !== key ? [r] : r.qty + delta > 0 ? [{ ...r, qty: r.qty + delta }] : [])),
    remove: (key) => setRows((prev) => prev.filter((r) => r.key !== key)),
    move: (key, section) => setRows((prev) => {
      const r = prev.find((x) => x.key === key);
      if (!r) return prev;
      const rest = prev.filter((x) => x.key !== key);
      const moved = section === "commander" ? 1 : r.qty;
      const back = section === "commander" && r.qty > 1 ? [{ ...r, qty: r.qty - 1 }] : [];   // лишние копии остаются в колоде
      const i = rest.findIndex((x) => x.section === section && (x.card ? x.card.id === r.card?.id : x.name === r.name));   // издание - у той строки, куда переносим
      if (i >= 0) return [...back, ...rest.map((x, j) => j === i ? { ...x, qty: section === "commander" ? 1 : x.qty + moved } : x)];
      return [...back, ...rest, { ...r, key: newKey(), section, qty: moved }];
    }),
  };

  async function patch(body: any) {
    const r = await api<any>(`/decks/${id}`, { method: "PATCH", body });
    setD({ ...d, ...r });
    setProblems(r.problems);
  }

  const saveLabel = { saved: "Сохранено", dirty: "Есть изменения…", saving: "Сохраняем…", error: "Не сохранено" }[save];
  return (
    <>
      <p className="muted small"><Link href="/me#decks">← Мои колоды</Link></p>
      <div className="deckhead">
        <input className="deckname" defaultValue={d.name} aria-label="Название колоды" maxLength={128}
          onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== d.name) run(() => patch({ name: v })); }} />
        <span className={`small ${save === "error" ? "loss" : "muted"}`} role="status">{saveLabel}{saveErr ? `: ${saveErr}` : ""}</span>
      </div>
      <div className="row">
        <label className="row" style={{ gap: 6 }}><span className="muted small">Формат</span>
          <select value={d.format} onChange={(e) => run(() => patch({ format: e.target.value }))} style={{ width: "auto" }}>
            {formats.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className="row" style={{ gap: 6 }}><span className="muted small">Доступ</span>
          <select value={d.visibility} onChange={(e) => run(() => patch({ visibility: e.target.value }))} style={{ width: "auto" }}
            title={VISIBILITY.find(([k]) => k === d.visibility)?.[2]}>
            {VISIBILITY.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <Link href={`/decks/${id}${d.visibility === "link" && d.share_key ? `?key=${d.share_key}` : ""}`} className="btn">Просмотр и тестовая рука</Link>
        <button type="button" onClick={() => setImporting(!importing)}>Импорт списка</button>
        <span className="seg" role="group" aria-label="Язык названий" style={{ marginLeft: "auto" }}>
          <button type="button" className={lang === "ru" ? "on" : ""} onClick={() => setLang("ru")}>RU</button>
          <button type="button" className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>EN</button>
        </span>
      </div>
      <p className="hint">{VISIBILITY.find(([k]) => k === d.visibility)?.[2]}.</p>
      <Status error={error} />
      {importing ? <ImportBox id={id} deck={d} hasCards={rows.length > 0} onDone={() => { setImporting(false); load(); }} /> : null}

      {printKey && rows.find((r) => r.key === printKey)?.card ? (
        <PrintPicker row={rows.find((r) => r.key === printKey)!} onClose={() => setPrintKey(null)} onPick={(card) => {
          setRows((prev) => prev.map((r) => r.key === printKey ? { ...r, card } : r));
          setPreview({ name: card.name, image: card.image_large || card.image_url, back: card.back_image });
        }} />
      ) : null}

      <CardSearch game={d.game} format={d.format} isCmd={isCmd} lang={lang} onAdd={add} onPreview={setPreview} />

      <div className="builder">
        <div>
          <p className="muted small" style={{ marginTop: 0 }}>
            В колоде {count(playing(rows))}{isCmd ? " из 100" : bk && d.format === "berserk" ? " (нужно от 30)" : ""}{rows.some((r) => r.section === "side") ? `, в сайдборде ${count(rows.filter((r) => r.section === "side"))}` : ""}.
            Наведите на карту, чтобы увидеть её; «⋯» — выбрать издание, перенести в сайдборд, сделать командиром или удалить.
          </p>
          <DeckList rows={rows} format={d.format} lang={lang} ops={ops}
            onHover={(r) => setPreview({ name: r.name, image: r.card?.image_url, back: r.card?.back_image })} />
        </div>
        <aside className="builder-side">
          <FlipCard front={preview?.image} back={preview?.back} alt={preview?.name || ""} className="previewimg" />
          <Problems problems={problems} />
          <DeckStats rows={rows} />
          <div className="section">
            <ConfirmButton className="danger" question="Удалить колоду?" confirmLabel="Удалить" danger disabled={busy}
              onConfirm={() => run(async () => { await api(`/decks/${id}`, { method: "DELETE" }); router.push("/me#decks"); })}>
              Удалить колоду
            </ConfirmButton>
          </div>
        </aside>
      </div>
    </>
  );
}

function CardSearch({ game, format, isCmd, lang, onAdd, onPreview }: {
  game: string; format: string; isCmd: boolean; lang: "ru" | "en";
  onAdd: (c: CardInfo, s: Row["section"], qty?: number) => void; onPreview: (p: { name: string; image?: string | null; back?: string | null }) => void;
}) {
  const [q, setQ] = useState("");
  const [legal, setLegal] = useState(true);
  const [items, setItems] = useState<CardInfo[] | null>(null);
  const [total, setTotal] = useState(0);
  const m = q.trim().match(/^(\d{1,2})\s*[xх]?\s+(.+)$/i);           // «4 lightning bolt» - сразу 4 копии
  const qty = m ? Math.max(1, Number(m[1])) : 1;
  const query = (m ? m[2] : q).trim();

  useEffect(() => {
    if (query.length < 2) { setItems(null); return; }
    const h = setTimeout(() => {
      const full = legal && game === "mtg" && format !== "casual" ? `${query} f:${format}` : query;
      api<any>(`/cards/search?${new URLSearchParams({ q: full, game, per_page: "12" })}`)
        .then((r) => { setItems(r.items); setTotal(r.total); }).catch(() => setItems([]));
    }, 250);
    return () => clearTimeout(h);
  }, [query, legal, format, game]);

  function pick(c: CardInfo, s: Row["section"]) {
    onAdd(c, s, qty);
  }
  return (
    <section className="cardpicker section">
      <form className="cardsearch" onSubmit={(e) => { e.preventDefault(); if (items?.[0]) { pick(items[0], "main"); setQ(""); } }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} autoFocus
          placeholder={game === "berserk" ? "Добавить карту: название, «3 Преторианец» или запрос el:горы t:существо"
            : "Добавить карту: название по-русски или по-английски, «4 Lightning Bolt» или запрос t:dragon c:r"}
          aria-label="Поиск карты для колоды" />
        <button type="submit" disabled={!items?.length}>Добавить</button>
      </form>
      <div className="row small">
        {game === "mtg" && format !== "casual" ? (
          <label className="check" style={{ margin: 0 }}>
            <input type="checkbox" checked={legal} onChange={(e) => setLegal(e.target.checked)} />
            <span>только легальные в формате</span>
          </label>
        ) : null}
        <span className="muted">Enter — первая карта в основную колоду. <Link href="/cards/syntax" target="_blank">Синтаксис поиска</Link></span>
      </div>
      {items ? (
        items.length ? (
          <ul className="pickresults">
            {items.map((c) => (
              <li key={c.id} onMouseEnter={() => onPreview({ name: c.name, image: c.image_url, back: c.back_image })}>
                <span className="cname">
                  <b>{lang === "ru" ? c.name_ru || c.name : c.name}</b>
                  <span className="muted small"> {lang === "ru" && c.name_ru ? c.name : c.name_ru || ""}</span>
                  <span className="muted small" style={{ display: "block" }}>{c.type}</span>
                </span>
                <span className="cost"><Mana text={bkCost(c).split(" // ")[0]} size={14} /></span>
                <span className="row" style={{ gap: 4 }}>
                  <button type="button" onClick={() => pick(c, "main")} title="В основную колоду">+{qty > 1 ? qty : ""}</button>
                  {game === "mtg" ? <button type="button" onClick={() => pick(c, "side")} title="В сайдборд">сайд</button> : null}
                  {isCmd ? <button type="button" onClick={() => onAdd(c, "commander")} title="Сделать командиром">командир</button> : null}
                </span>
              </li>
            ))}
            {total > items.length ? <li className="muted small">…и ещё {total - items.length}. Уточните запрос.</li> : null}
          </ul>
        ) : (
          <p className="muted small">
            Ничего не найдено{legal && game === "mtg" && format !== "casual" ? " среди легальных в формате — снимите галочку, чтобы искать везде" : ""}.
            {/[а-яё]/i.test(query) ? " У части карт в базе нет русского названия — попробуйте по-английски." : ""}
          </p>
        )
      ) : null}
    </section>
  );
}

function ImportBox({ id, deck, hasCards, onDone }: { id: string; deck: any; hasCards: boolean; onDone: () => void }) {
  const [text, setText] = useState("");
  const [report, setReport] = useState<any>(null);
  const { busy, error, run } = useAction();
  const go = () => run(async () => {
    const r = await api<any>(`/decks/${id}`, { method: "PUT", body: { name: deck.name, game: deck.game, text, format: deck.format } });
    setReport(r);
    if (!r.unmatched.length) onDone();
  });
  return (
    <div className="panel section">
      <h3 style={{ marginTop: 0 }}>Импорт списка</h3>
      <p className="muted small">Вставьте экспорт из Moxfield, MTGGoldfish, Archidekt, Arena или MTGO. Разделы «Commander», «Deck», «Sideboard» и строки «SB:» распознаются; командир последней строкой после пустой — тоже. Русские названия понимаются; издание вида «(CMM) 410» сохраняется.</p>
      <div className="row" style={{ marginBottom: 10 }}>
        <DeckFileInput onText={(t) => setText(t)} />
        <span className="muted small">или вставьте текст</span>
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} aria-label="Список карт"
        placeholder={"Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n35 Forest"} />
      <div className="row section" style={{ marginTop: 12 }}>
        {hasCards ? (
          <ConfirmButton className="primary" question="Заменить текущий список колоды?" confirmLabel="Заменить" disabled={busy || !text.trim()} onConfirm={go}>
            Заменить список
          </ConfirmButton>
        ) : <button type="button" className="primary" disabled={busy || !text.trim()} onClick={go}>Загрузить</button>}
      </div>
      <Status error={error} />
      {report?.unmatched?.length ? (
        <div>
          <p className="small">Загружено. Не найдены в базе ({report.unmatched.length}): {report.unmatched.slice(0, 20).join(", ")} — они остались в колоде с пометкой.</p>
          <button type="button" onClick={onDone}>Понятно</button>
        </div>
      ) : null}
    </div>
  );
}
