import type { Metadata } from "next";
import { Cormorant_Garamond, Golos_Text } from "next/font/google";
import Nav from "@/components/Nav";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

const display = Cormorant_Garamond({
  subsets: ["latin", "cyrillic"], weight: ["600", "700"], variable: "--font-display", display: "swap",
});
const body = Golos_Text({ subsets: ["latin", "cyrillic"], weight: ["400", "500", "600", "700"], variable: "--font-body", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Dragon — турниры клубов ККИ", template: "%s — Dragon" },
  description: "Турниры, рейтинги клубов, база карт, мета и аукционы для Magic: The Gathering, EDH и «Берсерка».",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={`${display.variable} ${body.variable}`}>
      <body>
        <AuthProvider>
          <Nav />
          <main className="wrap">{children}</main>
          <footer className="footer">
            <div className="wrap">
              Dragon — площадка для клубов и магазинов настольных игр. Сделки на аукционе проходят напрямую между игроками.
            </div>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
