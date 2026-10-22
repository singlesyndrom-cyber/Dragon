"use client";

import { useCallback, useEffect, useState } from "react";
import ArticleForm from "@/components/ArticleForm";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import CreatorRequestsAdmin, { StaffRoles } from "@/components/CreatorRequestsAdmin";
import Guard from "@/components/Guard";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { dateTime, rub } from "@/lib/format";

export default function AdminPage() {
  return <Guard moderator><AdminContent /></Guard>;
}

function AdminContent() {
  const { me } = useAuth();
  if (me?.role !== "admin") {   // модератор видит только заявки
    return (
      <>
        <h1>Модерация</h1>
        <CreatorRequestsAdmin />
      </>
    );
  }
  return (
    <>
      <h1>Админка</h1>
      <SystemHealth />
      <CreatorRequestsAdmin />
      <div className="split">
        <div>
          <Complaints />
          <Disputed />
          <Outbox />
          <CardImport />
        </div>
        <aside className="stack">
          <StaffRoles />
          <Scryfall />
          <Accounts />
          <Categories />
        </aside>
      </div>
      <ArticleForm clubId={null} />
    </>
  );
}

const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} МБ` : `${Math.max(1, Math.round(n / 1024))} КБ`);
const ago = (m: number | null) => (m === null ? "ни разу" : m < 1 ? "только что" : m < 60 ? `${Math.round(m)} мин назад` : `${Math.round(m / 60)} ч назад`);

/** Бот, очередь Telegram и резервные копии - одним взглядом; обновляется раз в минуту. */
function SystemHealth() {
  const [h, setH] = useState<any>(null);
  const load = useCallback(() => api("/admin/system").then(setH).catch(() => {}), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);
  if (!h) return null;
  const b = h.backups;
  return (
    <section className={`panel health ${h.ok ? "is-ok" : "is-bad"}`}>
      <h2 style={{ marginTop: 0 }}>Состояние системы: {h.ok ? "всё работает" : "нужно внимание"}</h2>
      {h.problems.length ? <ul>{h.problems.map((p: string) => <li key={p} className="err" style={{ margin: 0 }}>{p}</li>)}</ul> : null}
      <dl className="facts">
        <dt>Бот</dt><dd>последний сигнал {ago(h.bot.minutes_ago)}</dd>
        <dt>Очередь Telegram</dt>
        <dd>
          {h.outbox.pending ? `${h.outbox.pending} ждут отправки (самое старое ${ago(h.outbox.oldest_minutes)})` : "пусто"}
          {h.outbox.failed ? `, не отправлено: ${h.outbox.failed}` : ""}
          {h.outbox.last_sent_at ? <span className="muted">; последнее отправлено {dateTime(h.outbox.last_sent_at)}</span> : null}
        </dd>
        <dt>Резервные копии</dt>
        <dd>
          {!b.available ? <span className="muted">папка копий не подключена (обновите docker-compose.prod.yml)</span>
            : b.last ? <>{b.last.ok ? "последняя" : "ОШИБКА"} {dateTime(b.last.at)}{b.last.ok ? `, ${kb(b.last.size)} (облегчённая ${kb(b.last.light_size)})` : `: ${b.last.error}`}; всего файлов {b.files.length}</>
              : "ещё не было"}
        </dd>
      </dl>
      <p className="hint">Если бот молчит больше 5 минут, сообщения висят больше 10 минут или копии нет больше суток, администраторам уходит письмо.</p>
    </section>
  );
}

function Scryfall() {
  const [st, setSt] = useState<any>(null);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api("/admin/cards/sync/status").then(setSt).catch(() => {}), []);
  useEffect(() => {
    load();
    const h = setInterval(load, 10000);
    return () => clearInterval(h);
  }, [load]);
  const last = st?.last;
  return (
    <div className="panel">
      <h3>База MTG из Scryfall</h3>
      <p className="small muted">
        Загружается сама при первом запуске и обновляется раз в неделю. Полная загрузка с русскими названиями
        занимает 5–10 минут.
      </p>
      {st ? (
        <p className="small">
          {st.running ? "Идёт загрузка…" : last ? (
            <>Последняя: {dateTime(last.finished || last.started)} ({last.trigger === "auto" ? "автоматически" : "вручную"}),
              карт {last.cards.toLocaleString("ru-RU")}, русских названий {last.russian.toLocaleString("ru-RU")}.</>
          ) : "Ещё не загружалась."}
          {last?.error ? <span className="loss"> {last.error}</span> : null}
        </p>
      ) : null}
      <button className="primary" disabled={busy || st?.running}
        onClick={() => run(() => api("/admin/cards/sync/scryfall", { method: "POST" })).then(load)}>Обновить сейчас</button>
      <Status error={error} />
    </div>
  );
}

function CardImport() {
  const [game, setGame] = useState("berserk");
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const { busy, error, done, run } = useAction();
  const send = (dry: boolean) => run(async () => {
    if (!file) throw new Error("Выберите JSON-файл");
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", String(dry));
    if (mapping.trim()) form.append("mapping", mapping.trim());
    const r = await api(`/admin/cards/import/${game}`, { form });
    if (dry) setPreview(r); else { setPreview(null); return r; }
  }, dry ? "" : "Импорт завершён");
  return (
    <section>
      <h2>Импорт карт из JSON</h2>
      <p className="muted small">
        Для «Берсерка» и других игр. Поля распознаются по названиям на русском и английском. Сначала нажмите
        «Проверить»: увидите, как разберутся первые карты, ничего не записывая.
      </p>
      <div className="row inline">
        <label><span>Игра</span>
          <select value={game} onChange={(e) => setGame(e.target.value)}>
            <option value="berserk">Берсерк</option><option value="mtg">Magic: The Gathering</option>
          </select>
        </label>
        <label><span>Файл</span><input type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
      </div>
      <label><span>Соответствие полей, если автоопределение ошиблось (JSON)</span>
        <input value={mapping} placeholder='{"name": "title", "image_url": "pic"}' onChange={(e) => setMapping(e.target.value)} />
      </label>
      <div className="row">
        <button disabled={busy || !file} onClick={() => send(true)}>Проверить</button>
        <button className="primary" disabled={busy || !file} onClick={() => send(false)}>Импортировать</button>
      </div>
      <Status error={error} done={done} />
      {preview ? (
        <div className="panel">
          <p>Карт в файле: {preview.total}, будет загружено: {preview.would_import}, без названия: {preview.skipped_no_name}.</p>
          <pre className="small" style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>{JSON.stringify(preview.sample, null, 2)}</pre>
        </div>
      ) : null}
    </section>
  );
}

function Complaints() {
  const [items, setItems] = useState<any[]>([]);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api<any[]>("/admin/complaints").then(setItems).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  return (
    <section>
      <h2 style={{ marginTop: 0 }}>Жалобы</h2>
      {items.length ? (
        <ul className="news-list">
          {items.map((c) => (
            <li key={c.id}>
              <div className="small muted">
                {dateTime(c.created_at)}: {c.from_nick} (№{c.from_user_id}) на {c.against_nick} (№{c.against_user_id})
                {c.deal_id ? `, сделка ${c.deal_id}` : ""}
              </div>
              <p style={{ margin: "6px 0", whiteSpace: "pre-wrap" }}>{c.text}</p>
              <div className="row">
                <button disabled={busy} onClick={() => run(() => api(`/admin/complaints/${c.id}/resolve`, { method: "POST" })).then(load)}>Закрыть жалобу</button>
                <ConfirmButton className="danger" disabled={busy} question={`Заблокировать ${c.against_nick}?`} confirmLabel="Заблокировать"
                  onConfirm={() => run(() => api(`/admin/users/${c.against_user_id}/ban`, { body: { banned: true } }))}>
                  Заблокировать нарушителя
                </ConfirmButton>
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Открытых жалоб нет.</p>}
      <Status error={error} />
    </section>
  );
}

function Disputed() {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { api<any[]>("/admin/deals/disputed").then(setItems).catch(() => {}); }, []);
  if (!items.length) return null;
  return (
    <section>
      <h2>Спорные сделки</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Сделка</th><th>Продавец</th><th>Покупатель</th><th className="r">Цена</th></tr></thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.id}>
                <td><a href={`/auctions/${d.lot_id}`}>№{d.id}</a></td>
                <td>{d.seller_nick} (№{d.seller_id}): {d.seller_ok ? "состоялась" : "не состоялась"}</td>
                <td>{d.buyer_nick} (№{d.buyer_id}): {d.buyer_ok ? "состоялась" : "не состоялась"}</td>
                <td className="r">{rub(d.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Outbox() {
  const [items, setItems] = useState<any[]>([]);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api<any[]>("/admin/outbox?status=failed").then(setItems).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  if (!items.length) return null;
  return (
    <section>
      <h2>Неотправленные сообщения Telegram</h2>
      <p className="muted small">Чаще всего причина в том, что бота удалили из чата или пользователь не нажал Start.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Тип</th><th>Чат</th><th>Ошибка</th><th></th></tr></thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id}>
                <td>{m.kind}</td>
                <td className="num">{m.chat_id}</td>
                <td className="small">{m.error}</td>
                <td><button disabled={busy} onClick={() => run(() => api(`/admin/outbox/${m.id}/retry`, { method: "POST" })).then(load)}>Повторить</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Status error={error} />
    </section>
  );
}

/** Аккаунт по номеру игрока: карточка, блокировка, удаление (если нет истории), объединение с основным. */
function Accounts() {
  const [no, setNo] = useState("");
  const [u, setU] = useState<any>(null);
  const [into, setInto] = useState("");
  const { busy, error, done, run, setError } = useAction();
  const find = () => run(async () => { setU(null); setU(await api(`/admin/users/lookup/${no}`)); });
  const reload = () => api(`/admin/users/lookup/${u.player_no}`).then(setU).catch(() => setU(null));
  const history = u ? u.tournaments + u.matches + u.edh_seats + u.deals + u.lots + u.bids + u.tournaments_created : 0;
  return (
    <div className="panel">
      <h3>Аккаунты</h3>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (no) find(); }}>
        <input inputMode="numeric" placeholder="Номер игрока" aria-label="Номер игрока" value={no} style={{ maxWidth: 140 }}
          onChange={(e) => { setNo(e.target.value.replace(/\D/g, "")); setError(""); }} />
        <button disabled={busy || !no}>Найти</button>
      </form>
      {u ? (
        <div className="stack" style={{ marginTop: 12 }}>
          <div>
            <b>{u.nickname}</b> <span className="muted small">№{u.player_no}</span>
            {u.role === "admin" ? <span className="badge" style={{ marginLeft: 6 }}>админ</span> : null}
            {u.moderator ? <span className="badge" style={{ marginLeft: 6 }}>модератор</span> : null}
            {u.banned ? <span className="badge" style={{ marginLeft: 6, color: "var(--loss)" }}>заблокирован</span> : null}
          </div>
          <div className="small muted">
            {u.emails.join(", ") || "без email"} · Telegram {u.telegram ? "привязан" : "нет"} · с {dateTime(u.created_at)}<br />
            Клубов {u.clubs}, турниров {u.tournaments}, колод {u.decks}, сделок {u.deals}, лотов {u.lots}
          </div>
          <div className="row">
            <button className={u.banned ? undefined : "danger"} disabled={busy || u.role === "admin"}
              onClick={() => run(() => api(`/admin/users/${u.id}/ban`, { body: { banned: !u.banned } }).then(reload),
                u.banned ? "Блокировка снята" : "Пользователь заблокирован")}>
              {u.banned ? "Разблокировать" : "Заблокировать"}
            </button>
            <ConfirmButton className="link-btn" danger disabled={busy || history > 0 || u.role === "admin"}
              question={`Удалить аккаунт ${u.nickname} №${u.player_no} навсегда?`} confirmLabel="Удалить"
              onConfirm={() => run(async () => { await api(`/admin/users/${u.player_no}`, { method: "DELETE" }); setU(null); }, "Аккаунт удалён")}>
              удалить
            </ConfirmButton>
          </div>
          {history > 0 ? <p className="hint" style={{ margin: 0 }}>У игрока есть история — удалить нельзя, только объединить или заблокировать.</p> : null}
          <div className="row">
            <input inputMode="numeric" placeholder="Основной №" aria-label="Номер основного аккаунта" value={into} style={{ maxWidth: 140 }}
              onChange={(e) => setInto(e.target.value.replace(/\D/g, ""))} />
            <ConfirmButton disabled={busy || !into || into === String(u.player_no)}
              question={`Перенести всё из №${u.player_no} в №${into} и удалить №${u.player_no}?`} confirmLabel="Объединить"
              onConfirm={() => run(async () => {
                const r = await api<any>("/admin/users/merge", { body: { from_no: u.player_no, into_no: +into } });
                setNo(String(r.into)); setInto(""); setU(await api(`/admin/users/lookup/${r.into}`));
              }, "Аккаунты объединены")}>
              Объединить в основной
            </ConfirmButton>
          </div>
          <p className="hint" style={{ margin: 0 }}>Объединение переносит способы входа, турниры, колоды, сделки и клубы; очки лиги складываются.</p>
        </div>
      ) : null}
      <Status error={error} done={done} />
    </div>
  );
}

function Categories() {
  const [items, setItems] = useState<any[]>([]);
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();
  const load = useCallback(() => api<any[]>("/news/categories").then(setItems).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  return (
    <form className="panel" onSubmit={(e) => {
      e.preventDefault();
      run(() => api("/news/categories", { body: { name } })).then((ok) => { if (ok) { setName(""); load(); } });
    }}>
      <h3>Категории новостей</h3>
      <p className="small">{items.map((c) => c.name).join(", ") || <span className="muted">пока нет</span>}</p>
      <label><span>Новая категория</span><input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></label>
      <button disabled={busy}>Добавить</button>
      <Status error={error} />
    </form>
  );
}
