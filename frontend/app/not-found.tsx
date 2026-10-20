import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <h1>Страница не найдена</h1>
      <p className="lead">Возможно, турнир или статью удалили, или в адресе опечатка.</p>
      <Link href="/" className="btn">На главную</Link>
    </>
  );
}
