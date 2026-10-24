"use client";

/** Ошибка в самом каркасе сайта: показываем понятный текст и кнопку перезагрузки вместо «Application error». */
export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  const stale = /ChunkLoadError|Loading chunk|dynamically imported module|Importing a module script failed/i.test(`${error.name} ${error.message}`);
  return (
    <html lang="ru">
      <body style={{ background: "#141826", color: "#ece5d3", fontFamily: "system-ui, sans-serif", padding: 24 }}>
        <h2>Что-то пошло не так</h2>
        <p>{stale ? "Сайт обновился — нужно загрузить новую версию." : "Страница не открылась."}</p>
        <button type="button" onClick={() => window.location.reload()}
          style={{ background: "#c9a44c", color: "#141826", border: "none", borderRadius: 8, padding: "12px 20px", fontSize: 16 }}>
          Перезагрузить
        </button>
        <p style={{ color: "#9ba1b5", fontSize: 12, marginTop: 16, wordBreak: "break-word" }}>
          Для разработчиков: {error.name}: {error.message}{error.digest ? ` (${error.digest})` : ""}
        </p>
      </body>
    </html>
  );
}
