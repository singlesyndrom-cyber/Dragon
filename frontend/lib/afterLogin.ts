/** Куда вернуть игрока после входа или регистрации (например, на подтверждение привязки из бота). */
const KEY = "after_login";

export function rememberReturn(path: string) {
  try { if (path.startsWith("/")) window.sessionStorage.setItem(KEY, path); } catch {}
}

export function afterLogin(fallback = "/me"): string {
  try {
    const p = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    if (p && p.startsWith("/") && !p.startsWith("//")) return p;
  } catch {}
  return fallback;
}
