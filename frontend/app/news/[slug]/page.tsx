import Link from "next/link";
import { notFound } from "next/navigation";
import Comments from "@/components/Comments";
import Markdown from "@/components/Markdown";
import { sget } from "@/lib/api";
import { dateOnly } from "@/lib/format";

export default async function Article({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = await sget<any>(`/news/${encodeURIComponent(slug)}`);
  if (!a) notFound();
  return (
    <article>
      <h1>{a.title}</h1>
      <p className="muted">
        {a.club || "Dragon"}, {dateOnly(a.published_at)}
        {a.author ? `, автор ${a.author}` : ""}
      </p>
      {a.cover_url ? <img src={a.cover_url} alt="" style={{ maxWidth: "100%", borderRadius: 10, margin: "8px 0 20px" }} /> : null}
      {a.summary ? <p className="lead">{a.summary}</p> : null}
      <Markdown text={a.body_md} />
      {a.tags?.length ? (
        <div className="tags">
          {a.tags.map((t: any) => <Link key={t.slug} className="badge" href={`/news?tag=${t.slug}`}>#{t.name}</Link>)}
        </div>
      ) : null}
      <h2>Комментарии</h2>
      <Comments slug={a.slug} />
    </article>
  );
}
