"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import CreatorRequest from "@/components/CreatorRequest";
import Guard from "@/components/Guard";
import TelegramLogin from "@/components/TelegramLogin";
import VkButton from "@/components/VkButton";
import { api } from "@/lib/api";
import { VISIBILITY, formatTitle } from "@/lib/decks";
import { useAuth } from "@/lib/auth";
import { rub } from "@/lib/format";
import { JUDGE_GAMES } from "@/lib/judges";

const DEAL: Record<string, string> = {
  pending: "Ждёт подтверждения", completed: "Состоялась", failed: "Не состоялась", disputed: "Спорная",
};

export default function MePage() {
  return <Guard><Cabinet /></Guard>;
}

function Cabinet() {
  const { me, reload } = useAuth();
  const [rating, setRating] = useState<any>(null);
  useEffect(() => { if (me) api(`/auctions/users/${me.id}/rating`).then(setRating).catch(() => {}); }, [me]);
  const link = useAction();
  useEffect(() => {   // вернулись с VK ID после привязки - обновить способы входа
    if (window.location.search.includes("vk=linked")) {
      reload();
      window.history.replaceState(null, "", "/me");
    }
  }, [reload]);
  const onTelegram = useCallback((data: Record<string, unknown>) => {
    link.run(() => api("/auth/telegram/link", { body: data }), "Telegram привязан").then((ok) => { if (ok) reload(); });
  }, [link, reload]);
  if (!me) return null;
  return (
    <>
      <h1>{me.nickname}</h1>
      {me.player_no ? (
        <p className="lead" style={{ marginTop: 0 }}>
          Ваш номер игрока <b className="num">{me.player_no}</b>. Назовите его организатору, чтобы он записал вас на турнир;
          по нему же другие игроки видят вашу <Link href={`/players/${me.player_no}`}>репутацию на аукционе</Link>.
        </p>
      ) : null}
      <div className="split">
        <div>
          <Decks />
          <Deals />
        </div>
        <aside className="stack">
          <MyBookings />
          <MyClubs />
          <CreatorRequest />
          <div className="panel">
            <h3>Аккаунт</h3>
            <p className="muted small">Способы входа: {me.providers.map((p) => ({ email: "email", telegram: "Telegram", vk: "VK" } as any)[p] || p).join(", ")}</p>
            {!me.providers.includes("telegram") ? (
              <>
                <p className="small">Привяжите Telegram, чтобы делать ставки на аукционе от этого аккаунта и получать уведомления.</p>
                <TelegramLogin onAuth={onTelegram} />
                <Status error={link.error} done={link.done} />
              </>
            ) : null}
            {!me.providers.includes("vk") ? (
              <div className="section" style={{ marginTop: 16 }}>
                <p className="small">Привяжите VK — чтобы входить через VK и получать напоминания от сообщества клуба.</p>
                <VkButton purpose="link" label="Привязать VK" />
              </div>
            ) : null}
          </div>
          {me.providers.includes("email") ? <ChangePassword /> : null}
          {rating ? (
            <div className="panel">
              <h3>Репутация на аукционе</h3>
              <dl className="facts">
                <dt>Как продавец</dt><dd>{rating.seller_count ? `${rating.seller_avg} из 5 (${rating.seller_count})` : "оценок нет"}</dd>
                <dt>Как покупатель</dt><dd>{rating.buyer_count ? `${rating.buyer_avg} из 5 (${rating.buyer_count})` : "оценок нет"}</dd>
                <dt>Сделок</dt><dd>{rating.deals_completed}</dd>
              </dl>
            </div>
          ) : null}
        </aside>
      </div>
    </>
  );
}

function ChangePassword() {
  const { signIn } = useAuth();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ old_password: "", new_password: "", repeat: "" });
  const { busy, error, done, run, setError } = useAction();
  if (!open) {
    return (
      <div className="panel">
        <h3>Пароль</h3>
        <button type="button" onClick={() => setOpen(true)}>Сменить пароль</button>
        <Status done={done} />
      </div>
    );
  }
  return (
    <form className="panel" onSubmit={(e) => {
      e.preventDefault();
      if (f.new_password !== f.repeat) { setError("Новые пароли не совпадают"); return; }
      run(async () => {
        const r = await api("/auth/password/change", { body: { old_password: f.old_password, new_password: f.new_password } });
        await signIn(r.access_token);
        setF({ old_password: "", new_password: "", repeat: "" });
        setOpen(false);
      }, "Пароль изменён. На других устройствах нужно войти заново.");
    }}>
      <h3>Смена пароля</h3>
      <label><span>Текущий пароль</span><input type="password" required autoComplete="current-password" value={f.old_password} onChange={(e) => setF({ ...f, old_password: e.target.value })} /></label>
      <label><span>Новый, не короче 8 символов</span><input type="password" required minLength={8} autoComplete="new-password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></label>
      <label><span>Повторите новый</span><input type="password" required minLength={8} autoComplete="new-password" value={f.repeat} onChange={(e) => setF({ ...f, repeat: e.target.value })} /></label>
      <div className="row">
        <button className="primary" disabled={busy}>Сохранить</button>
        <button type="button" className="link-btn" onClick={() => { setOpen(false); setError(""); }}>Отмена</button>
      </div>
      <Status error={error} />
    </form>
  );
}

function Decks() {
  const [decks, setDecks] = useState<any[]>([]);
  const { busy, error, run } = useAction();
  const load = () => api<any[]>("/decks/mine").then(setDecks).catch(() => {});
  useEffect(() => { load(); }, []);
  return (
    <section id="decks">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Колоды</h2>
        <span className="row" style={{ gap: 8 }}>
          <Link href="/decks" className="btn">Каталог колод</Link>
          <Link href="/decks/new" className="btn primary">Новая колода</Link>
        </span>
      </div>
      {decks.length ? (
        <ul className="news-list">
          {decks.map((d) => (
            <li key={d.id} className="row" style={{ justifyContent: "space-between", padding: "10px 0" }}>
              <span>
                <Link href={`/decks/${d.id}`}>{d.name}</Link>{" "}
                <span className="muted small">
                  {d.game === "mtg" ? formatTitle(d.format) : "Берсерк"} · {d.cards} карт · {VISIBILITY.find(([k]) => k === d.visibility)?.[1]}
                </span>
              </span>
              <span className="row" style={{ gap: 14 }}>
                <Link href={`/decks/${d.id}/edit`} className="small">Редактировать</Link>
                <label className="check small" style={{ margin: 0 }} title="Колода анонимно попадёт в блок «Популярное у игроков» в разделе Мета">
                  <input type="checkbox" checked={d.in_meta} disabled={busy}
                    onChange={(e) => run(() => api(`/decks/${d.id}`, { method: "PATCH", body: { in_meta: e.target.checked } })).then(load)} />
                  <span>в мете</span>
                </label>
                <ConfirmButton className="link-btn" question={`Удалить «${d.name}»?`} confirmLabel="Удалить" danger disabled={busy}
                  onConfirm={() => run(() => api(`/decks/${d.id}`, { method: "DELETE" })).then(load)}>Удалить</ConfirmButton>
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Колод пока нет. Соберите колоду в конструкторе или вставьте готовый список из Moxfield, MTGGoldfish или Arena.</p>}
      <Status error={error} />
    </section>
  );
}

function Deals() {
  const [deals, setDeals] = useState<any[]>([]);
  const { busy, error, done, run } = useAction();
  const load = () => api<any[]>("/auctions/deals/mine").then(setDeals).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!deals.length) return null;
  return (
    <section>
      <h2>Сделки на аукционе</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Лот</th><th>Роль</th><th>С кем</th><th className="r">Цена</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {deals.map((d) => (
              <tr key={d.id}>
                <td><Link href={`/auctions/${d.lot_id}`}>{d.title}</Link></td>
                <td>{d.role === "seller" ? "продавец" : "покупатель"}</td>
                <td>{d.counterparty_no ? <Link href={`/players/${d.counterparty_no}`}>{d.counterparty} <span className="muted small">№{d.counterparty_no}</span></Link> : d.counterparty}</td>
                <td className="r">{rub(d.price)}</td>
                <td>{DEAL[d.status]}</td>
                <td>
                  {d.status === "pending" && d.my_answer === null ? (
                    <div className="row">
                      <button disabled={busy} onClick={() => run(() => api(`/auctions/deals/${d.id}/confirm`, { body: { ok: true } })).then(load)}>Состоялась</button>
                      <button disabled={busy} className="danger" onClick={() => run(() => api(`/auctions/deals/${d.id}/confirm`, { body: { ok: false } })).then(load)}>Не состоялась</button>
                    </div>
                  ) : d.status === "completed" ? (
                    <select defaultValue="" disabled={busy} aria-label="Оценка"
                      onChange={(e) => run(() => api(`/auctions/deals/${d.id}/rate`, { body: { score: +e.target.value } }), "Оценка сохранена")}>
                      <option value="" disabled>Оценить</option>
                      {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Status error={error} done={done} />
    </section>
  );
}

/** Будущие брони столов во всех клубах; отмена - с подтверждением. */
function MyBookings() {
  const [rows, setRows] = useState<any[] | null>(null);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api<any[]>("/bookings/mine").then(setRows).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);
  if (!rows?.length) return null;
  return (
    <div className="panel">
      <h3>Мои брони столов</h3>
      <ul className="news-list">
        {rows.map((b) => (
          <li key={b.id} style={{ padding: "8px 0" }}>
            <div><b>{b.table}</b> · <Link href={`/clubs/${b.club_slug}/tables`}>{b.club}</Link></div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="num small">{b.when}</span>
              <ConfirmButton className="link-btn" danger disabled={busy} question="Отменить бронь?" confirmLabel="Отменить"
                onConfirm={() => run(async () => { await api(`/bookings/${b.id}`, { method: "DELETE" }); await load(); })}>
                отменить
              </ConfirmButton>
            </div>
          </li>
        ))}
      </ul>
      <Status error={error} />
    </div>
  );
}

function MyClubs() {
  const { me } = useAuth();
  const [clubs, setClubs] = useState<any[] | null>(null);
  const [judging, setJudging] = useState<any[]>([]);
  const { busy, error, run } = useAction();
  const load = useCallback(() => api<any[]>("/clubs/mine").then(setClubs).catch(() => setClubs([])), []);
  useEffect(() => {
    load();
    api<any[]>("/clubs/judging").then(setJudging).catch(() => {});
  }, [load]);
  if (clubs === null) return null;
  return (
    <div className="panel">
      <h3>Мои клубы</h3>
      {clubs.length ? (
        <ul className="news-list">
          {clubs.map((c) => (
            <li key={c.id} style={{ padding: "10px 0" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <Link href={`/clubs/${c.slug}`}><b>{c.name}</b></Link>
                {c.organizer ? <span className="badge">организатор</span> : null}
              </div>
              <div className="muted small">
                Очки лиги {c.league_points} · банк EDH {Math.round(c.edh_bank).toLocaleString("ru-RU")} · ивентов {c.events_played}
              </div>
              <div className="row small" style={{ marginTop: 4, gap: 14 }}>
                <Link href={`/clubs/${c.slug}`}>{c.upcoming ? `Турниры: ${c.upcoming} с открытой записью` : "Турниры клуба"}</Link>
                {c.tables ? <Link href={`/clubs/${c.slug}/tables`}>Забронировать стол</Link> : null}
                {c.staff ? (
                  <label className="check" style={{ margin: 0 }} title="Сообщения бота в личку о новых бронях столов и отменах">
                    <input type="checkbox" checked={c.booking_notify} disabled={busy}
                      onChange={(e) => run(async () => { await api(`/clubs/${c.id}/booking-notify`, { method: "PUT", body: { enabled: e.target.checked } }); await load(); })} />
                    <span>брони в Telegram</span>
                  </label>
                ) : null}
                {c.organizer ? <Link href={`/tournaments/new?club=${c.id}`}>Создать турнир</Link> : (
                  <ConfirmButton className="link-btn" danger disabled={busy}
                    question={`Выйти из клуба «${c.name}»? Очки лиги и банк EDH в нём обнулятся, будущие брони отменятся.`}
                    confirmLabel="Выйти" onConfirm={() => run(async () => { await api(`/clubs/${c.id}/leave`, { method: "POST" }); await load(); })}>
                    выйти
                  </ConfirmButton>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="small muted">Вы пока не состоите в клубах. <Link href="/clubs">Найдите свой клуб</Link> и вступите — запись на турниры и бронь столов станут в один клик.</p>}
      <Status error={error} />
      {judging.length ? (
        <>
          <h3 style={{ marginTop: 16 }}>Судейство</h3>
          <ul className="news-list">
            {judging.map((c) => (
              <li key={c.id} className="row" style={{ justifyContent: "space-between", padding: "8px 0" }}>
                <Link href={`/clubs/${c.slug}`}>{c.name}</Link>
                <span className="muted small">{c.games.map((g: string) => JUDGE_GAMES[g]).join(", ")}</span>
                <Link href={`/manage/clubs/${c.id}/members`} className="small">Участники</Link>
              </li>
            ))}
          </ul>
          <p className="small muted" style={{ margin: 0 }}>Турнир ведётся кнопкой «Управлять турниром» на его странице.</p>
        </>
      ) : null}
      {me?.is_club_creator ? <Link href="/clubs/new" className="btn" style={{ marginTop: 12 }}>Создать клуб</Link>
        : <p className="small muted" style={{ marginBottom: 0 }}>Чтобы открыть свой клуб, получите статус «Создатель Клуба»: заявка ниже.</p>}
    </div>
  );
}
