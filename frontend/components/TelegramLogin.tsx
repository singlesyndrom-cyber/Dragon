"use client";

import { useEffect, useRef } from "react";

const BOT = process.env.NEXT_PUBLIC_TG_BOT_NAME;

/** Официальный виджет входа Telegram. Домен сайта нужно указать боту в BotFather (/setdomain). */
export default function TelegramLogin({ onAuth }: { onAuth: (data: Record<string, unknown>) => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!BOT || !box.current) return;
    (window as any).__dragonTgAuth = onAuth;
    const s = document.createElement("script");
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.async = true;
    s.setAttribute("data-telegram-login", BOT);
    s.setAttribute("data-size", "large");
    s.setAttribute("data-radius", "4");
    s.setAttribute("data-request-access", "write");
    s.setAttribute("data-onauth", "__dragonTgAuth(user)");
    box.current.innerHTML = "";
    box.current.appendChild(s);
  }, [onAuth]);
  if (!BOT) return null;
  return <div ref={box} />;
}
