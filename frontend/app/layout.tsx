import type { Metadata } from "next";
import Link from "next/link";
import Nav from "@/components/Nav";
import SwRegister from "@/components/SwRegister";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

// Шрифты грузит браузер при открытии страницы: сборка не зависит от доступа к Google Fonts.
const FONTS = "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Golos+Text:wght@400;500;600;700&display=swap";

export const metadata: Metadata = {
  title: { default: "Dragon — турниры клубов ККИ", template: "%s — Dragon" },
  description: "Турниры, рейтинги клубов, база карт, мета и аукционы для Magic: The Gathering, EDH и «Берсерка».",
};

export const viewport = { themeColor: "#141826" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>
        <AuthProvider>
          <Nav />
          <SwRegister />
          <main className="wrap">{children}</main>
          <footer className="footer">
            <div className="wrap footer-row">
              <span>Dragon — площадка для клубов и магазинов настольных игр. Сделки на аукционе проходят напрямую между игроками.</span>
              <nav aria-label="О сайте" className="footer-links">
                <Link href="/about">О проекте: данные и разработка</Link>
                <a href="/guides/dragon-mtg.pdf" target="_blank" rel="noopener">Путеводитель MTG</a>
                <a href="/guides/dragon-berserk.pdf" target="_blank" rel="noopener">Путеводитель «Берсерк»</a>
                <a href="/guides/dragon-publisher.pdf" target="_blank" rel="noopener">Для издателей</a>
              </nav>
            </div>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
