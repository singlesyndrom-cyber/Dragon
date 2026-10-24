"use client";

import { useEffect } from "react";

/** Регистрирует service worker (офлайн для «За столом»). Только в продакшене. */
export default function SwRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  return null;
}
