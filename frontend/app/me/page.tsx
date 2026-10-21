"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import CreatorRequest from "@/components/CreatorRequest";
import Guard from "@/components/Guard";
import TelegramLogin from "@/components/TelegramLogin";
import { api } from "@/lib/api";
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
  const [f, setF] = useState({ name: "", game: "mtg", commander: "", text: "" });
  const [report, setReport] = useState<any>(null);
  const { busy, error, run } = useAction();
  const load = () => api<any[]>("/decks/mine").then(setDecks).catch(() => {});
  useEffect(() => { load(); }, []);
  return (
    <section id="decks">
      <h2 style={{ marginTop: 0 }}>Колоды</h2>
      {decks.length ? (
        <ul className="news-list">
          {decks.map((d) => (
            <li key={d.id} className="row" style={{ justifyContent: "space-between", padding: "10px 0" }}>
              <span>{d.name} <span className="muted small">{d.game === "mtg" ? "MTG" : "Берсерк"}</span></span>
              <button className="link-btn" onClick={() =>
                run(() => api(`/decks/${d.id}`, { method: "DELETE" })).then(load)}>Удалить</button>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Колод пока нет. Добавьте список, чтобы подавать его на турниры.</p>}

      <form className="section" onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const body: any = { name: f.name, game: f.game, text: f.text };
          if (f.commander.trim()) body.commander = f.commander.trim();
          setReport(await api("/decks", { body }));
          setF({ ...f, name: "", commander: "", text: "" });
          load();
        });
      }}>
        <h3>Новая колода</h3>
        <div className="row inline">
          <label><span>Название</span><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label><span>Игра</span>
            <select value={f.game} onChange={(e) => setF({ ...f, game: e.target.value })}>
              <option value="mtg">Magic: The Gathering</option>
              <option value="berserk">Берсерк</option>
            </select>
          </label>
        </div>
        <label><span>Командир, если его нет в списке</span><input value={f.commander} onChange={(e) => setF({ ...f, commander: e.target.value })} /></label>
        <label><span>Список карт: экспорт из Moxfield, Archidekt или строки вида «1 Sol Ring»</span>
          <textarea required value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} style={{ minHeight: 200 }} />
        </label>
        <button className="primary" disabled={busy}>Сохранить колоду</button>
        <Status error={error} />
      </form>
      {report ? (
        <div className="panel">
          <p style={{ margin: 0 }}>Сохранено, карт в основной колоде: {report.cards}.</p>
          {report.warnings.map((w: string) => <p key={w} className="small" style={{ margin: "6px 0 0" }}>{w}</p>)}
          {report.unmatched.length ? <p className="muted small">Не найдены в базе: {report.unmatched.slice(0, 20).join(", ")}</p> : null}
        </div>
      ) : null}
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

function MyClubs() {
  const { me } = useAuth();
  const [clubs, setClubs] = useState<any[] | null>(null);
  const [judging, setJudging] = useState<any[]>([]);
  useEffect(() => {
    api<any[]>("/clubs/managed").then(setClubs).catch(() => setClubs([]));
    api<any[]>("/clubs/judging").then(setJudging).catch(() => {});
  }, []);
  if (clubs === null) return null;
  return (
    <div className="panel">
      <h3>Мои клубы</h3>
      {clubs.length ? (
        <ul className="news-list">
          {clubs.map((c) => (
            <li key={c.id} className="row" style={{ justifyContent: "space-between", padding: "8px 0" }}>
              <Link href={`/clubs/${c.slug}`}>{c.name}</Link>
              <Link href={`/tournaments/new?club=${c.id}`} className="small">Создать турнир</Link>
            </li>
          ))}
        </ul>
      ) : <p className="small muted">{me?.is_club_creator ? "Создайте клуб, чтобы проводить турниры и вести лигу." : "Чтобы открыть свой клуб, получите статус «Создатель Клуба»: заявка ниже."}</p>}
      {judging.length ? (
        <>
          <h3 style={{ marginTop: 16 }}>Судейство</h3>
          <ul className="news-list">
            {judging.map((c) => (
              <li key={c.id} className="row" style={{ justifyContent: "space-between", padding: "8px 0" }}>
                <Link href={`/clubs/${c.slug}`}>{c.name}</Link>
                <span className="muted small">{c.games.map((g: string) => JUDGE_GAMES[g]).join(", ")}</span>
              </li>
            ))}
          </ul>
          <p className="small muted" style={{ margin: 0 }}>Турнир ведётся кнопкой «Управлять турниром» на его странице.</p>
        </>
      ) : null}
      {me?.is_club_creator ? <Link href="/clubs/new" className="btn" style={{ marginTop: 12 }}>Создать клуб</Link> : null}
    </div>
  );
}
