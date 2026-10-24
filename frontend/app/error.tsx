"use client";

import { useEffect } from "react";

const KEY = "dragon_reloaded_at";

/** Ошибка на странице. Самая частая причина в установленном приложении - сайт обновился, а открытая
 *  страница ищет файлы старой версии (ChunkLoadError): тогда один раз тихо перезагружаемся. */
function stale(e: Error) {
  return /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i
    .test(`${e.name} ${e.message}`);
}

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    if (!stale(error)) return;
    try {
      const last = Number(window.sessionStorage.getItem(KEY) || 0);
      if (Date.now() - last < 15000) return;          // уже перезагружались - не зацикливаемся
      window.sessionStorage.setItem(KEY, String(Date.now()));
    } catch {}
    window.location.reload();
  }, [error]);

  return (
    <section className="panel" style={{ marginTop: 24 }}>
      <h2 style={{ marginTop: 0 }}>Что-то пошло не так</h2>
      <p>{stale(error) ? "Сайт обновился — загружаем новую версию." : "Страница не открылась. Попробуйте ещё раз."}</p>
      <div className="row">
        <button type="button" className="primary" onClick={() => window.location.reload()}>Перезагрузить</button>
        <button type="button" onClick={() => reset()}>Повторить</button>
      </div>
      <p className="muted small" style={{ marginTop: 12, wordBreak: "break-word" }}>
        Для разработчиков: {error.name}: {error.message}{error.digest ? ` (${error.digest})` : ""}
      </p>
    </section>
  );
}
