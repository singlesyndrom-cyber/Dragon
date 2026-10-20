"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";

export default function Comments({ slug }: { slug: string }) {
  const { me, ready } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [text, setText] = useState("");
  const { busy, error, run } = useAction();

  const load = useCallback(() => {
    api<any[]>(`/news/${encodeURIComponent(slug)}/comments`).then(setItems).catch(() => setItems([]));
  }, [slug]);
  useEffect(() => { if (ready) load(); }, [ready, me, load]);

  // поле is_hidden приходит только модераторам статьи
  const moderator = items.some((c) => "is_hidden" in c);

  return (
    <div>
      {items.length ? (
        <ul className="news-list">
          {items.map((c) => (
            <li key={c.id} style={c.is_hidden ? { opacity: 0.5 } : undefined}>
              <div className="row small">
                <b>{c.nickname}</b>
                <span className="muted">{dateTime(c.created_at)}</span>
                {c.is_hidden ? <span className="badge">скрыт</span> : null}
              </div>
              <p style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{c.body}</p>
              <div className="row small">
                {moderator ? (
                  <button className="link-btn" onClick={() =>
                    run(() => api(`/news/comments/${c.id}/${c.is_hidden ? "unhide" : "hide"}`, { method: "POST" })).then(load)}>
                    {c.is_hidden ? "Показать" : "Скрыть"}
                  </button>
                ) : null}
                {me && (me.id === c.user_id || moderator) ? (
                  <button className="link-btn" onClick={() =>
                    run(() => api(`/news/comments/${c.id}`, { method: "DELETE" })).then(load)}>Удалить</button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Комментариев пока нет.</p>}

      {me ? (
        <form className="section" onSubmit={(e) => {
          e.preventDefault();
          run(() => api(`/news/${encodeURIComponent(slug)}/comments`, { body: { body: text } })).then((ok) => {
            if (ok) { setText(""); load(); }
          });
        }}>
          <label><span>Ваш комментарий</span>
            <textarea required maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 90 }} />
          </label>
          <button className="primary" disabled={busy || !text.trim()}>Отправить</button>
        </form>
      ) : ready ? <p><Link href="/login">Войдите</Link>, чтобы написать комментарий.</p> : null}
      <Status error={error} />
    </div>
  );
}
