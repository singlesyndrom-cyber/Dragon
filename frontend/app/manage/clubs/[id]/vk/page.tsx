"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";
import ConfirmButton from "@/components/ConfirmButton";
import { Status, useAction } from "@/components/Form";
import Guard from "@/components/Guard";
import VkButton from "@/components/VkButton";
import { api } from "@/lib/api";

export default function ClubVkPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <Guard><Suspense fallback={<p className="muted">Загружаем…</p>}><ClubVk clubId={Number(id)} /></Suspense></Guard>;
}

function ClubVk({ clubId }: { clubId: number }) {
  const q = useSearchParams();
  const [v, setV] = useState<any>(undefined);
  const [err, setErr] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const base = `/clubs/${clubId}/vk`;
  const load = () => api(base).then(setV).catch((e) => { setErr(e.message); setV(null); });
  useEffect(() => { load(); }, [clubId]);

  if (v === undefined) return <p className="muted">Загружаем…</p>;
  if (!v) return <p>{err || "Настраивать VK могут только организаторы клуба."}</p>;
  const apply = (x: any) => { setV(x); setWarnings(x.warnings || []); };

  return (
    <>
      <p className="muted small"><Link href={`/manage/clubs/${clubId}`}>← Управление клубом</Link></p>
      <h1>ВКонтакте</h1>
      <p className="lead">Анонсы турниров с кнопкой «Записаться» и итоги — в беседу клуба и на стену сообщества;
        напоминания о турнирах и бронях — игрокам в личку от сообщества.</p>
      {q.get("wall") === "connected" ? <p className="win">Стена подключена.</p> : null}
      {warnings.map((w) => <p key={w} className="hint">{w}</p>)}
      {v.last_error ? <div className="panel deckproblems is-bad"><b>Последняя ошибка доставки</b><p className="small" style={{ margin: "6px 0 0" }}>{v.last_error}</p></div> : null}
      <div className="stack section" style={{ maxWidth: 760 }}>
        <Community clubId={clubId} v={v} onChange={apply} />
        {v.has_group_token ? <Chat clubId={clubId} v={v} onChange={apply} reload={load} /> : null}
        {v.has_group_token ? <Wall clubId={clubId} v={v} onChange={apply} /> : null}
        {v.has_group_token ? <Dms clubId={clubId} v={v} onChange={apply} /> : null}
        {v.has_group_token ? (
          <div>
            <ConfirmButton className="danger" question="Отключить VK от клуба? Токены будут удалены." confirmLabel="Отключить" danger
              onConfirm={() => api(base, { method: "DELETE" }).then(load)}>Отключить VK</ConfirmButton>
          </div>
        ) : null}
      </div>
    </>
  );
}

type P = { clubId: number; v: any; onChange: (x: any) => void };

function Community({ clubId, v, onChange }: P) {
  const [token, setToken] = useState("");
  const { busy, error, done, run } = useAction();
  return (
    <section className="panel">
      <h2 style={{ marginTop: 0 }}>1. Сообщество</h2>
      {v.has_group_token ? (
        <p>Подключено: <a href={`https://vk.com/club${v.group_id}`} target="_blank" rel="noreferrer">{v.group_name}</a></p>
      ) : <p className="muted">Сообщество ещё не подключено.</p>}
      <details open={!v.has_group_token}>
        <summary>{v.has_group_token ? "Заменить токен сообщества" : "Как подключить"}</summary>
        <ol className="small steps">
          <li>В сообществе VK: «Управление» → «Сообщения» → включите сообщения сообщества.</li>
          <li>«Управление» → «Сообщения» → «Настройки для бота»: включите «Возможности ботов» и «Разрешать добавлять сообщество в беседы».</li>
          <li>«Управление» → «Работа с API» → «Ключи доступа» → «Создать ключ» с правами «Управление сообществом» и «Сообщения сообщества». Скопируйте ключ.</li>
          <li>Вставьте ключ ниже. Long Poll API сайт включит сам.</li>
        </ol>
        <form className="row" onSubmit={(e) => {
          e.preventDefault();
          run(async () => { onChange(await api(`/clubs/${clubId}/vk`, { method: "PUT", body: { group_token: token } })); setToken(""); }, "Сообщество подключено");
        }}>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="vk1.a.…" autoComplete="off"
            aria-label="Ключ доступа сообщества" style={{ flex: 1, minWidth: 220 }} />
          <button className="primary" disabled={busy || token.trim().length < 20}>Подключить</button>
        </form>
        <p className="muted small">Ключ хранится на сервере в зашифрованном виде и больше нигде не показывается.</p>
      </details>
      <Status error={error} done={done} />
    </section>
  );
}

function Toggle({ clubId, field, value, label, onChange }: { clubId: number; field: string; value: boolean; label: string; onChange: (x: any) => void }) {
  const { busy, error, run } = useAction();
  return (
    <>
      <label className="check">
        <input type="checkbox" checked={value} disabled={busy}
          onChange={(e) => run(async () => onChange(await api(`/clubs/${clubId}/vk`, { method: "PUT", body: { [field]: e.target.checked } })))} />
        <span>{label}</span>
      </label>
      <Status error={error} />
    </>
  );
}

function TestButton({ clubId, target, chatId, disabled }: { clubId: number; target: "chat" | "wall"; chatId?: number; disabled?: boolean }) {
  const { busy, error, done, run } = useAction();
  return (
    <span>
      <button type="button" disabled={busy || disabled} onClick={() =>
        run(() => api(`/clubs/${clubId}/vk/test`, { body: { target, chat_id: chatId } }), "Отправлено — проверьте VK через минуту")}>
        Тестовое сообщение
      </button>
      <Status error={error} done={done} />
    </span>
  );
}

function Chat({ clubId, v, onChange, reload }: P & { reload: () => void }) {
  const games: Record<string, string> = v.games || {};
  const [game, setGame] = useState(Object.keys(games).find((g) => !v.chats.some((c: any) => c.game === g)) || "all");
  const { busy, error, run } = useAction();
  const call = (path: string, method: string, body?: any) =>
    run(async () => onChange(await api(`/clubs/${clubId}/vk${path}`, { method, body })));
  return (
    <section className="panel">
      <h2 style={{ marginTop: 0 }}>2. Беседы клуба</h2>
      <p className="small muted" style={{ marginTop: 0 }}>Каждой игре — своя беседа: анонсы и итоги турниров уходят в беседу игры турнира.
        Беседа «Все игры и новости» получает новости клуба и турниры игр, у которых своей беседы нет.</p>
      {v.chats.length ? (
        <ul className="vkchats">
          {v.chats.map((c: any) => (
            <li key={c.id}>
              <span className="cname"><b>{c.title || `Беседа №${c.peer_id - 2000000000}`}</b></span>
              <select value={c.game} disabled={busy} aria-label="Игра беседы" style={{ width: "auto" }}
                onChange={(e) => call(`/chats/${c.id}`, "PATCH", { game: e.target.value })}>
                {Object.entries(games).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              <TestButton clubId={clubId} target="chat" chatId={c.id} />
              <ConfirmButton className="link-btn" question="Отключить беседу?" confirmLabel="Отключить" disabled={busy}
                onConfirm={() => call(`/chats/${c.id}`, "DELETE")}>Отключить</ConfirmButton>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Беседы ещё не подключены.</p>}

      {v.bind_code ? (
        <div className="panel" style={{ background: "var(--vellum-2)" }}>
          <p style={{ marginTop: 0 }}>Код для беседы «{games[v.bind_game] || "Все игры и новости"}»:{" "}
            <b className="num" style={{ fontSize: "1.4rem" }}>{v.bind_code}</b></p>
          <ol className="small steps">
            <li>Сообщество «{v.group_name}» должно быть участником беседы: в беседе «Добавить участника» → вкладка «Сообщества».</li>
            <li>Отправьте в беседу: <code>@club{v.group_id} {v.bind_code}</code> — с упоминанием, иначе сообщество сообщение не увидит.</li>
            <li>Бот ответит «Беседа подключена». Нажмите «Проверить».</li>
          </ol>
          <div className="row">
            <button type="button" onClick={reload}>Проверить</button>
            <button type="button" className="link-btn" onClick={() => call("/bind", "DELETE")}>Отменить</button>
          </div>
        </div>
      ) : (
        <div className="row section" style={{ marginTop: 12 }}>
          <span className="small">Подключить беседу для</span>
          <select value={game} onChange={(e) => setGame(e.target.value)} aria-label="Игра" style={{ width: "auto" }}>
            {Object.entries(games).map(([k, l]) => (
              <option key={k} value={k}>{l}{v.chats.some((c: any) => c.game === k) ? " (заменить)" : ""}</option>
            ))}
          </select>
          <button type="button" disabled={busy} onClick={() => call("/bind", "POST", { game })}>Получить код привязки</button>
        </div>
      )}
      <div className="section" style={{ marginTop: 12 }}>
        <Toggle clubId={clubId} field="chat_enabled" value={v.chat_enabled} label="Отправлять анонсы и итоги в беседы" onChange={onChange} />
      </div>
      <Status error={error} />
    </section>
  );
}

function Wall({ clubId, v, onChange }: P) {
  const [token, setToken] = useState("");
  const { busy, error, done, run } = useAction();
  return (
    <section className="panel">
      <h2 style={{ marginTop: 0 }}>3. Стена сообщества</h2>
      <p className="muted small">VK разрешает публиковать на стене только от имени администратора сообщества, поэтому здесь нужен
        вход администратора, а не ключ сообщества.</p>
      {v.wall_connected ? (
        <>
          <p>Подключено{v.wall_user_name ? ` через ${v.wall_user_name}` : ""}{v.wall_mode === "token" ? " (ключ вручную)" : ""}.</p>
          <div className="row">
            <Toggle clubId={clubId} field="wall_enabled" value={v.wall_enabled} label="Публиковать анонсы, итоги и новости клуба" onChange={onChange} />
            <TestButton clubId={clubId} target="wall" />
            <ConfirmButton question="Отключить стену?" confirmLabel="Отключить"
              onConfirm={() => run(async () => onChange(await api(`/clubs/${clubId}/vk/wall`, { method: "DELETE" })))}>Отключить стену</ConfirmButton>
          </div>
        </>
      ) : (
        <>
          {v.vkid_enabled ? (
            <>
              <p className="small">Войдите через VK как администратор сообщества «{v.group_name}» и разрешите публикации на стене.</p>
              <VkButton purpose="wall" label="Подключить стену через VK" clubId={clubId} scope="vkid.personal_info wall groups" />
            </>
          ) : <p className="small muted">Вход через VK ID на сайте не настроен — используйте ключ администратора ниже.</p>}
          <details className="section" style={{ marginTop: 16 }} open={!v.vkid_enabled}>
            <summary className="small">Вставить ключ администратора вручную</summary>
            <p className="small muted">Ключ доступа пользователя-администратора с правами wall и offline (бессрочный). Хранится зашифрованным.</p>
            <form className="row" onSubmit={(e) => {
              e.preventDefault();
              run(async () => { onChange(await api(`/clubs/${clubId}/vk/wall/token`, { method: "PUT", body: { token } })); setToken(""); }, "Стена подключена");
            }}>
              <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" aria-label="Ключ администратора"
                style={{ flex: 1, minWidth: 220 }} />
              <button disabled={busy || token.trim().length < 20}>Подключить</button>
            </form>
          </details>
        </>
      )}
      <Status error={error} done={done} />
    </section>
  );
}

function Dms({ clubId, v, onChange }: P) {
  return (
    <section className="panel">
      <h2 style={{ marginTop: 0 }}>4. Личные сообщения игрокам</h2>
      <p className="small">Напоминания о турнире за сутки, о брони за 2 часа, место из листа ожидания и сообщения о бронях
        организаторам — от имени сообщества. Получат те, кто привязал VK на сайте и разрешил сообщения сообществу
        (достаточно один раз написать сообществу «Начать»).</p>
      <p className="small"><a href={`https://vk.com/im?sel=-${v.group_id}`} target="_blank" rel="noreferrer">Ссылка для игроков: написать сообществу</a></p>
      <Toggle clubId={clubId} field="dm_enabled" value={v.dm_enabled} label="Отправлять личные напоминания через VK" onChange={onChange} />
    </section>
  );
}
