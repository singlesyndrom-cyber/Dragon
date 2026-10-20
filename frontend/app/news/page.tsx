import Link from "next/link";
import { sget } from "@/lib/api";
import { dateOnly } from "@/lib/format";

export const metadata = { title: "Новости" };

export default async function News({ searchParams }: { searchParams: Promise<{ tag?: string; category?: string; q?: string }> }) {
  const sp = await searchParams;
  const qs = new URLSearchParams({ limit: "40" });
  if (sp.tag) qs.set("tag", sp.tag);
  if (sp.category) qs.set("category", sp.category);
  if (sp.q) qs.set("q", sp.q);
  const [items, cats] = await Promise.all([sget<any[]>(`/news?${qs}`), sget<any[]>("/news/categories")]);
  return (
    <>
      <h1>Новости</h1>
      <form className="row inline" action="/news">
        <input name="q" placeholder="Поиск по заголовкам" defaultValue={sp.q || ""} />
        <select name="category" defaultValue={sp.category || ""}>
          <option value="">Все категории</option>
          {(cats || []).map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
        </select>
        <button>Найти</button>
        {sp.tag ? <span className="muted">Тег: {sp.tag} <Link href="/news">сбросить</Link></span> : null}
      </form>
      {items?.length ? (
        <ul className="news-list section">
          {items.map((a) => (
            <li key={a.id}>
              <h3><Link href={`/news/${a.slug}`}>{a.title}</Link></h3>
              <div className="muted small">
                {a.club || "Dragon"}, {dateOnly(a.published_at)}
                {a.comments ? `, комментариев: ${a.comments}` : ""}
              </div>
              {a.summary ? <p style={{ marginTop: 8 }}>{a.summary}</p> : null}
            </li>
          ))}
        </ul>
      ) : <p className="muted section">Ничего не нашлось.</p>}
    </>
  );
}
