"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import { api } from "@/lib/api";

/** Экран судьи для драфта: рассадка по столам, таймеры пиков и просмотра, сборка колоды, затем таймер тура.
 *  Выводится на ТВ или проектор; таймер считается от времени сервера, поэтому экран можно перезагрузить. */
export default function DraftPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><DraftScreen id={id} /></Guard>;
}

type Step = { kind: "pick" | "review" | "build"; pack?: number; pick?: number; cards_left?: number; direction?: string; seconds: number };

const DIR = { left: "налево ⟵", right: "направо ⟶" } as Record<string, string>;

function mmss(sec: number) {
  const s = Math.max(0, Math.ceil(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Текущий этап по «сырому» состоянию (так же, как на сервере, app/draft.py: current). */
function locate(timeline: Step[], raw: any, nowMs: number) {
  if (!raw?.started_at) return { stage: "seating" as const };
  const started = Date.parse(raw.started_at);
  const at = raw.paused_at ? Date.parse(raw.paused_at) : nowMs;
  const t = (at - started) / 1000 + Number(raw.offset || 0);
  let acc = 0;
  for (let i = 0; i < timeline.length; i++) {
    const s = timeline[i];
    if (t < acc + s.seconds) return { stage: s.kind, index: i, step: s, left: acc + s.seconds - t, next: timeline[i + 1], paused: !!raw.paused_at };
    acc += s.seconds;
  }
  return { stage: "done" as const };
}

let audio: AudioContext | null = null;
const VOLUME: Record<string, number> = { off: 0, low: 0.07, mid: 0.16, high: 0.32 };

/** Мягкий колокольчик: синус с тихим обертоном, плавное нарастание и затухание - без щелчков. */
function chime(notes: number[], volume: number, gap = 0.28, decay = 1.1) {
  if (!volume) return;
  try {
    audio = audio || new AudioContext();
    const t0 = audio.currentTime + 0.02;
    notes.forEach((freq, i) => {
      const at = t0 + i * gap;
      for (const [mult, part] of [[1, 1], [2, 0.18], [3, 0.06]] as const) {     // основной тон и обертоны
        const o = audio!.createOscillator(), g = audio!.createGain();
        o.type = "sine";
        o.frequency.value = freq * mult;
        g.gain.setValueAtTime(0.0001, at);
        g.gain.exponentialRampToValueAtTime(volume * part, at + 0.015);
        g.gain.exponentialRampToValueAtTime(0.0001, at + decay / mult);
        o.connect(g); g.connect(audio!.destination);
        o.start(at); o.stop(at + decay + 0.05);
      }
    });
  } catch {}
}
const SOUNDS = {
  pick: (v: number) => chime([784], v * 0.6, 0, 0.45),                 // новый пик: короткий тихий «динь»
  stage: (v: number) => chime([659, 880], v),                          // смена этапа: два тона вверх
  end: (v: number) => chime([880, 659, 523], v, 0.35, 1.6),            // конец сборки или тура: три тона вниз
};

function DraftScreen({ id }: { id: string }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  const [skew, setSkew] = useState(0);                 // время сервера минус время этого устройства, мс
  const [now, setNow] = useState(Date.now());
  const [sound, setSound] = useState<string>(() => {
    try { return localStorage.getItem("draft-sound") || "mid"; } catch { return "mid"; }
  });
  const vol = VOLUME[sound] ?? VOLUME.mid;
  const { busy, error, run } = useAction();
  const lastIndex = useRef<number | string | null>(null);

  const load = useCallback(async () => {
    const x = await api<any>(`/tournaments/${id}/draft`);
    setSkew(Date.parse(x.server_now) - Date.now());
    setD(x);
  }, [id]);
  useEffect(() => { load().catch((e) => setErr(e.message)); }, [load]);
  useEffect(() => { const h = setInterval(() => setNow(Date.now()), 200); return () => clearInterval(h); }, []);
  useEffect(() => { const h = setInterval(() => load().catch(() => {}), 10000); return () => clearInterval(h); }, [load]);

  const serverNow = now + skew;
  const cur: any = d ? locate(d.timeline, d.raw, serverNow) : null;
  const roundLeft = d?.round_started_at && d.round_minutes
    ? Date.parse(d.round_started_at) + d.round_minutes * 60000 - serverNow : null;

  // звук: короткий сигнал на каждом новом пике, длинный - на смене этапа и в конце тура
  const marker = cur ? (cur.stage === "done" && d.round ? `round-${d.round}-${roundLeft != null && roundLeft <= 0}` : cur.index ?? cur.stage) : null;
  useEffect(() => {
    if (marker === null || lastIndex.current === null) { lastIndex.current = marker; return; }
    if (marker !== lastIndex.current && vol && !cur?.paused) {
      const kind = cur?.step?.kind;
      if (kind === "pick" && cur.step.pick > 1) SOUNDS.pick(vol);
      else if (typeof marker === "string" && marker.startsWith("round-")) {
        if (marker.endsWith("-true")) SOUNDS.end(vol); else SOUNDS.stage(vol);   // конец тура / начало тура
      } else if (cur?.stage === "done") SOUNDS.end(vol);                          // сборка колоды окончена
      else SOUNDS.stage(vol);
    }
    lastIndex.current = marker;
  }, [marker]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <p>{err === "Это не драфт-турнир" ? "Это не драфт-турнир." : err}</p>;
  if (!d) return <p className="muted">Загружаем…</p>;
  const ctl = (action: string, seconds?: number) =>
    run(async () => { await api(`/tournaments/${id}/draft/control`, { body: { action, seconds } }); await load(); });
  const c = d.config;
  const pods: Record<number, any[]> = {};
  for (const s of d.seating) if (s.pod) (pods[s.pod] = pods[s.pod] || []).push(s);
  const unseated = d.seating.filter((s: any) => !s.seat && !s.dropped);
  const picksPerPack = c.cards - 1;

  return (
    <div className="draftscreen">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="muted small" style={{ margin: 0 }}><Link href={`/manage/tournaments/${id}`}>← Управление турниром</Link></p>
        <span className="row small" style={{ gap: 10 }}>
          <label className="row" style={{ margin: 0, gap: 6 }}><span className="muted">Звук</span>
            <select value={sound} style={{ width: "auto" }} onChange={(e) => {
              setSound(e.target.value);
              try { localStorage.setItem("draft-sound", e.target.value); } catch {}
              SOUNDS.stage(VOLUME[e.target.value]);
            }}>
              <option value="off">выключен</option><option value="low">тихо</option>
              <option value="mid">средне</option><option value="high">громко</option>
            </select>
          </label>
          <button type="button" onClick={() => { SOUNDS.pick(vol); setTimeout(() => SOUNDS.stage(vol), 700); setTimeout(() => SOUNDS.end(vol), 1900); }}>
            Проверить звук</button>
          <button type="button" onClick={() => document.documentElement.requestFullscreen?.().catch(() => {})}>На весь экран</button>
        </span>
      </div>

      {/* ---------- драфт идёт ---------- */}
      {cur.stage === "pick" || cur.stage === "review" || cur.stage === "build" ? (
        <section className={`dclock ${cur.paused ? "paused" : ""} ${cur.left <= 5 && cur.stage !== "build" ? "hot" : ""}`}>
          {cur.stage === "pick" ? (
            <>
              <p className="dlabel">Бустер {cur.step.pack} из {c.boosters}{c.sets ? ` · ${c.sets}` : ""}</p>
              <p className="ddir">Передаём {DIR[cur.step.direction]}</p>
              <p className="dtime">{mmss(cur.left)}</p>
              <p className="dlabel">Пик {cur.step.pick} из {picksPerPack} · в бустере {cur.step.cards_left} карт</p>
            </>
          ) : cur.stage === "review" ? (
            <>
              <p className="ddir">Просмотр взятых карт</p>
              <p className="dtime">{mmss(cur.left)}</p>
              <p className="dlabel">После бустера {cur.step.pack}{cur.step.pack < c.boosters ? `. Дальше бустер ${cur.step.pack + 1}: передаём ${DIR[cur.next?.direction]}` : ""}</p>
            </>
          ) : (
            <>
              <p className="ddir">Сборка колоды и регистрация деклиста</p>
              <p className="dtime">{mmss(cur.left)}</p>
              <p className="dlabel">Затем тур 1 · {d.round_minutes} минут</p>
            </>
          )}
          {cur.paused ? <p className="dpause">ПАУЗА</p> : null}
          {cur.next && cur.stage === "pick" ? (
            <p className="muted small">Дальше: {cur.next.kind === "pick" ? `пик ${cur.next.pick}, ${cur.next.seconds} с` : cur.next.kind === "review" ? "просмотр карт" : "сборка колоды"}</p>
          ) : null}
          <div className="row dctl">
            {cur.paused ? <button type="button" className="primary" disabled={busy} onClick={() => ctl("resume")}>Продолжить</button>
              : <button type="button" disabled={busy} onClick={() => ctl("pause")}>Пауза</button>}
            <button type="button" disabled={busy} onClick={() => ctl("add", 15)}>+15 с</button>
            {cur.stage === "build" ? <button type="button" disabled={busy} onClick={() => ctl("add", 300)}>+5 мин</button> : null}
            <button type="button" disabled={busy} onClick={() => ctl("skip")}>Следующий этап</button>
          </div>
        </section>
      ) : null}

      {/* ---------- драфт окончен: туры ---------- */}
      {cur.stage === "done" ? (
        <section className="dclock">
          {d.status === "registration" ? (
            <>
              <p className="ddir">Драфт и сборка колод завершены</p>
              <p className="dlabel">Первый тур — {c.first_round === "seats" ? "с сидящим напротив за своим столом" : "случайные пары"}, {d.round_minutes} минут.</p>
              <div className="row dctl">
                <button type="button" className="primary" disabled={busy}
                  onClick={() => run(async () => { await api(`/tournaments/${id}/start?force=true`, { method: "POST" }); await load(); })}>
                  Запустить тур 1</button>
              </div>
            </>
          ) : d.status === "running" && roundLeft != null ? (
            <>
              <p className="dlabel">Тур {d.round} из {d.rounds_total}</p>
              <p className={`dtime ${roundLeft <= 0 ? "over" : roundLeft <= 5 * 60000 ? "hot" : ""}`}>{roundLeft > 0 ? mmss(roundLeft / 1000) : "Время!"}</p>
              <p className="dlabel">{roundLeft > 0 ? `Лимит тура ${d.round_minutes} минут`
                : d.game === "berserk" ? "Время! Второй игрок завершает ход, судья может добавить до 5 минут (Турнирные правила, 704.4)"
                : "Время! Дополнительные ходы по правилам турнира"}</p>
              <div className="row dctl">
                <Link href={`/manage/tournaments/${id}`} className="btn primary">Пары и результаты</Link>
              </div>
            </>
          ) : <p className="ddir">Турнир завершён</p>}
        </section>
      ) : null}

      {/* ---------- подготовка: рассадка и настройки ---------- */}
      {cur.stage === "seating" ? (
        <section className="section">
          <h1 style={{ marginBottom: 4 }}>Драфт{c.sets ? ` ${c.sets}` : ""}</h1>
          <p className="muted" style={{ marginTop: 0 }}>
            {c.boosters} бустера по {c.cards} карт · просмотр {c.review_first}/{c.review_first + c.review_step}/{c.review_first + 2 * c.review_step} с ·
            сборка {c.build_minutes} мин · туры по {c.round_minutes} мин
          </p>
          <div className="row">
            <button type="button" className={d.seating.some((s: any) => s.seat) ? "" : "primary"} disabled={busy}
              onClick={() => run(async () => { await api(`/tournaments/${id}/draft/seat`, { method: "POST" }); await load(); })}>
              {d.seating.some((s: any) => s.seat) ? "Пересадить заново" : "Рассадить игроков"}</button>
            <button type="button" className="primary" disabled={busy || !d.seating.some((s: any) => s.seat)}
              onClick={() => ctl("start")}>Начать драфт</button>
          </div>
          {unseated.length && d.seating.some((s: any) => s.seat) ? (
            <p className="hint">Без места: {unseated.map((s: any) => s.nickname).join(", ")} — рассадите заново.</p>
          ) : null}
          <Config id={id} c={c} reload={load} />
        </section>
      ) : null}

      <Status error={error} />

      {Object.keys(pods).length ? (
        <section className="section">
          <h2>Рассадка</h2>
          <div className="pods">
            {Object.entries(pods).map(([pod, ss]) => (
              <div key={pod} className="panel">
                <h3 style={{ marginTop: 0 }}>Стол {pod}</h3>
                <ol className="seats">
                  {ss.map((s: any) => <li key={s.user_id} value={s.seat}><b className="num">{s.seat}</b> {s.nickname}</li>)}
                </ol>
                <p className="muted small" style={{ margin: 0 }}>Передача налево — к следующему месту по часовой.</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Config({ id, c, reload }: { id: string; c: any; reload: () => Promise<void> }) {
  const [f, setF] = useState<any>(c);
  useEffect(() => setF(c), [c]);
  const { busy, error, done, run } = useAction();
  const num = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const counts = Array.from({ length: Math.max(0, Number(f.cards) - 1) }, (_, i) => Number(f.cards) - i);
  return (
    <details className="panel section">
      <summary>Настройки драфта</summary>
      <div className="row inline" style={{ marginTop: 10 }}>
        <label><span>Бустеры (выпуски)</span><input value={f.sets} onChange={num("sets")} style={{ width: 140 }} /></label>
        <label><span>Бустеров</span><input type="number" min={1} max={6} value={f.boosters} onChange={num("boosters")} style={{ width: 80 }} /></label>
        <label><span>Карт в бустере</span><input type="number" min={2} max={30} value={f.cards} onChange={num("cards")} style={{ width: 80 }} /></label>
        <label><span>Сборка, мин</span><input type="number" min={1} max={180} value={f.build_minutes} onChange={num("build_minutes")} style={{ width: 80 }} /></label>
        <label><span>Тур, мин</span><input type="number" min={10} max={180} value={f.round_minutes} onChange={num("round_minutes")} style={{ width: 80 }} /></label>
        <label><span>Просмотр, с</span><input type="number" min={0} max={900} value={f.review_first} onChange={num("review_first")} style={{ width: 80 }} /></label>
        <label><span>+ за бустер, с</span><input type="number" min={0} max={900} value={f.review_step} onChange={num("review_step")} style={{ width: 80 }} /></label>
        <label><span>Игроков за столом, макс.</span><input type="number" min={2} max={32} value={f.pod_max} onChange={num("pod_max")} style={{ width: 80 }} /></label>
        <label><span>Первый тур</span>
          <select value={f.first_round} onChange={num("first_round")}>
            <option value="seats">По рассадке (напротив)</option>
            <option value="random">Случайно</option>
          </select>
        </label>
      </div>
      <p className="small" style={{ marginBottom: 4 }}>Секунд на пик по числу карт в бустере (последняя карта — без таймера):</p>
      <div className="picktimes">
        {counts.map((n) => (
          <label key={n}><span className="muted small">{n} карт</span>
            <input type="number" min={1} max={600} value={f.pick_seconds?.[String(n)] ?? ""} style={{ width: 64 }}
              onChange={(e) => setF({ ...f, pick_seconds: { ...f.pick_seconds, [String(n)]: e.target.value } })} />
          </label>
        ))}
      </div>
      <p className="muted small">По умолчанию: Magic — таблица MTR (приложение B), 40 с при 15–14 картах … 5 с при 4–2, просмотр
        60/90/120 с, столы до 8 игроков. «Берсерк» — Турнирные правила (п. 601): бустер 12 карт, 60…10 с на пик, просмотр 1 минута,
        столы 8–16 игроков, число столов — степень двойки, первый тур — жеребьёвка (п. 705), тур 45 минут рекомендовано (п. 704.3).</p>
      <button type="button" className="primary" disabled={busy}
        onClick={() => run(async () => {
          const body = { ...f, pod_max: +f.pod_max, boosters: +f.boosters, cards: +f.cards, build_minutes: +f.build_minutes, round_minutes: +f.round_minutes,
            review_first: +f.review_first, review_step: +f.review_step,
            pick_seconds: Object.fromEntries(Object.entries(f.pick_seconds || {}).map(([k, v]) => [k, +(v as any)])) };
          await api(`/tournaments/${id}/draft/config`, { method: "PUT", body });
          await reload();
        }, "Сохранено")}>Сохранить настройки</button>
      <Status error={error} done={done} />
    </details>
  );
}
