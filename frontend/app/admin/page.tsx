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
          <Ban />
          <Categories />
        </aside>
      </div>
      <ArticleForm clubId={null} />
    </>
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

function Ban() {
  const [uid, setUid] = useState("");
  const { busy, error, done, run } = useAction();
  const go = (banned: boolean) => run(() => api(`/admin/users/${uid}/ban`, { body: { banned } }),
    banned ? "Пользователь заблокирован" : "Блокировка снята");
  return (
    <div className="panel">
      <h3>Блокировка</h3>
      <label><span>ID пользователя</span><input inputMode="numeric" value={uid} onChange={(e) => setUid(e.target.value.replace(/\D/g, ""))} /></label>
      <div className="row">
        <button className="danger" disabled={busy || !uid} onClick={() => go(true)}>Заблокировать</button>
        <button disabled={busy || !uid} onClick={() => go(false)}>Разблокировать</button>
      </div>
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
