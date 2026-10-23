"use client";

import { useEffect, useState } from "react";

/** Язык названий карт в колодах (RU/EN), запоминается в браузере. */
export function useLang(): ["ru" | "en", (l: "ru" | "en") => void] {
  const [lang, setLangState] = useState<"ru" | "en">("en");
  useEffect(() => {
    try {
      const v = localStorage.getItem("deck-lang");
      if (v === "ru" || v === "en") setLangState(v);
    } catch {}
  }, []);
  function setLang(l: "ru" | "en") {
    setLangState(l);
    try { localStorage.setItem("deck-lang", l); } catch {}
  }
  return [lang, setLang];
}
