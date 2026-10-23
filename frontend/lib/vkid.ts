/** VK ID без SDK: OAuth 2.1 с PKCE. Браузер уходит на id.vk.ru, возвращается на /auth/vk с кодом,
 *  а обмен кода на токен делает сервер (секрет code_verifier живёт только в этой вкладке). */
import { api } from "@/lib/api";

export type VkPurpose = "login" | "link" | "wall";
type Pending = { state: string; verifier: string; purpose: VkPurpose; clubId?: number; back?: string };
const KEY = "vkid_pending";
const CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-";

function randomString(n: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return Array.from(bytes, (b) => CHARS[b % CHARS.length]).join("");
}

async function challenge(verifier: string): Promise<string> {
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  return btoa(String.fromCharCode(...hash)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export type VkConfig = { enabled: boolean; app_id: string | null; redirect_uri: string | null };
let cached: Promise<VkConfig> | null = null;
export function vkConfig(): Promise<VkConfig> {
  cached = cached || api<VkConfig>("/auth/vk/config").catch(() => ({ enabled: false, app_id: null, redirect_uri: null }));
  return cached;
}

/** Уйти на VK ID. scope "wall groups" - для публикаций на стене сообщества. */
export async function startVk(purpose: VkPurpose, opts: { clubId?: number; back?: string; scope?: string } = {}) {
  const cfg = await vkConfig();
  if (!cfg.enabled || !cfg.app_id || !cfg.redirect_uri) throw new Error("Вход через VK пока не настроен");
  const pending: Pending = { state: randomString(40), verifier: randomString(64), purpose, clubId: opts.clubId, back: opts.back };
  try { sessionStorage.setItem(KEY, JSON.stringify(pending)); } catch { throw new Error("Браузер не дал сохранить данные входа"); }
  const q = new URLSearchParams({
    response_type: "code", client_id: cfg.app_id, redirect_uri: cfg.redirect_uri, state: pending.state,
    code_challenge: await challenge(pending.verifier), code_challenge_method: "S256",
    scope: opts.scope || "vkid.personal_info",
  });
  location.assign(`https://id.vk.ru/authorize?${q}`);
}

export function takePending(): Pending | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
