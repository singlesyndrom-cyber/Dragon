"use client";

import { useEffect, useState } from "react";
import { Status, useAction } from "@/components/Form";
import { api } from "@/lib/api";

export default function ArticleForm({ clubId }: { clubId: number | null }) {
  const [cats, setCats] = useState<any[]>([]);
  const [f, setF] = useState({ title: "", summary: "", body_md: "", category: "", tags: "", cover_url: "", publish: true });
  const { busy, error, done, run } = useAction();
  useEffect(() => { api<any[]>("/news/categories").then(setCats).catch(() => {}); }, []);
  return (
    <form className="section" onSubmit={(e) => {
      e.preventDefault();
      run(async () => {
        await api("/news", { body: {
          club_id: clubId, title: f.title, summary: f.summary, body_md: f.body_md, publish: f.publish,
          category: f.category || null, cover_url: f.cover_url.trim() || null,
          tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
        } });
        setF({ ...f, title: "", summary: "", body_md: "", tags: "", cover_url: "" });
      }, f.publish ? "Опубликовано" : "Черновик сохранён");
    }}>
      <h2>{clubId ? "Новость клуба" : "Статья"}</h2>
      <label><span>Заголовок</span><input required minLength={3} maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
      <label><span>Кратко, для ленты</span><input maxLength={500} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} /></label>
      <label><span>Текст в Markdown</span><textarea required value={f.body_md} onChange={(e) => setF({ ...f, body_md: e.target.value })} style={{ minHeight: 220 }} /></label>
      <div className="row inline">
        <label><span>Категория</span>
          <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
            <option value="">Без категории</option>
            {cats.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
          </select>
        </label>
        <label><span>Теги через запятую</span><input value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} /></label>
      </div>
      <label><span>Ссылка на обложку</span><input type="url" value={f.cover_url} onChange={(e) => setF({ ...f, cover_url: e.target.value })} /></label>
      <label className="row"><input type="checkbox" checked={f.publish} onChange={(e) => setF({ ...f, publish: e.target.checked })} /> Опубликовать сразу</label>
      <button className="primary" disabled={busy}>{f.publish ? "Опубликовать" : "Сохранить черновик"}</button>
      <Status error={error} done={done} />
    </form>
  );
}
