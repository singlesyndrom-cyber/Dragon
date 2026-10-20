"use client";

import { useState } from "react";

/** Хук для действий формы: занятость, текст ошибки и успеха. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  async function run(fn: () => Promise<unknown>, success = "") {
    setBusy(true);
    setError("");
    setDone("");
    try {
      await fn();
      if (success) setDone(success);
      return true;
    } catch (e: any) {
      setError(e?.message || "Что-то пошло не так");
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, done, run, setError };
}

export function Status({ error, done }: { error?: string; done?: string }) {
  return (
    <div aria-live="polite">
      {error ? <p className="err">{error}</p> : null}
      {done ? <p className="ok">{done}</p> : null}
    </div>
  );
}
