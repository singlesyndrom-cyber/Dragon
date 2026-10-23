"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS = [
  ["/tournaments", "Турниры"],
  ["/leagues", "Лиги"],
  ["/clubs", "Клубы"],
  ["/news", "Новости"],
  ["/cards", "Картотека"],
  ["/decks", "Колоды"],
  ["/meta", "Мета"],
  ["/auctions", "Аукцион"],
] as const;

export default function Nav() {
  const path = usePathname();
  const { me, ready, signOut } = useAuth();
  return (
    <header className="top">
      <div className="wrap">
        <Link href="/" className="brand">Dragon</Link>
        <nav className="nav" aria-label="Разделы">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href} aria-current={path.startsWith(href) ? "page" : undefined}>{label}</Link>
          ))}
        </nav>
        <div className="who">
          {!ready ? null : me ? (
            <>
              {me.role === "admin" ? <Link href="/admin">Админка</Link> : me.is_moderator ? <Link href="/admin">Модерация</Link> : null}
              {me.is_publisher && me.role !== "admin" ? <Link href="/publisher">Издатель</Link> : null}
              <Link href="/me">{me.nickname}</Link>
              <button className="link-btn" onClick={signOut}>Выйти</button>
            </>
          ) : (
            <>
              <Link href="/login">Войти</Link>
              <Link href="/register" className="btn primary">Регистрация</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
