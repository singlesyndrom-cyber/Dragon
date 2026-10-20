/*
 * Сквозной тест в настоящем браузере: путь организатора кнопками, как это делает человек.
 * Запуск на поднятом стеке (docker compose up): BASE=http://localhost:3000 API=http://localhost:8000 node organizer.mjs
 * Скриншоты каждого шага - в папке shots/ (CI сохраняет их как артефакт).
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE || "http://localhost:3000";
const API = process.env.API || "http://localhost:8000";
mkdirSync("shots", { recursive: true });

const step = (n) => console.log(`\n▶ ${n}`);
const visible = async (locator, msg) => {
  await locator.first().waitFor({ state: "visible", timeout: 15000 }).catch(() => { throw new Error("ПРОВЕРКА НЕ ПРОШЛА: " + msg); });
  console.log("  ✓", msg);
};
const check = (cond, msg) => { if (!cond) throw new Error("ПРОВЕРКА НЕ ПРОШЛА: " + msg); console.log("  ✓", msg); };

async function apiCall(path, { token, method, body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(API + path, { method: method || (body ? "POST" : "GET"), headers, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  if (!r.ok) throw new Error(`${path}: ${r.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

const run = Date.now().toString(36);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
let n = 0;
const shot = async (name) => page.screenshot({ path: `shots/${String(++n).padStart(2, "0")}-${name}.png`, fullPage: true });

try {
  step("Регистрация организатора через форму");
  await page.goto(BASE + "/register");
  await page.getByLabel("Ник").fill("Организатор E2E");
  await page.getByLabel("Email").fill(`org-${run}@example.com`);
  await page.getByLabel("Пароль").fill("e2e-password-1");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await page.waitForURL("**/me");
  await visible(page.getByRole("heading", { name: "Мои клубы" }), "в кабинете есть блок «Мои клубы»");
  await shot("cabinet");

  step("Создание клуба с русским названием");
  await page.getByRole("link", { name: "Создать клуб" }).first().click();
  await page.getByLabel("Название").fill(`Клуб Е2Е ${run}`);
  await page.getByLabel("Город").fill("Казань");
  await page.getByRole("button", { name: "Создать клуб" }).click();
  await page.waitForURL(/\/clubs\/klub-e2e-/);
  await visible(page.getByRole("heading", { name: `Клуб Е2Е ${run}` }), "страница клуба открылась по латинскому адресу");
  await shot("club");

  step("Кнопка «Создать турнир» на странице турниров");
  await page.goto(BASE + "/tournaments");
  await visible(page.getByRole("link", { name: "Создать турнир" }), "на странице турниров есть «Создать турнир»");
  await page.getByRole("link", { name: "Создать турнир" }).first().click();
  await page.waitForURL(/\/manage\/clubs\/\d+/);
  await page.getByLabel("Название").first().fill("Е2Е швейцарка");
  await page.getByLabel("Туров").fill("2");
  await page.getByRole("button", { name: "Создать турнир" }).click();
  await page.waitForURL(/\/manage\/tournaments\/\d+/);
  const tid = page.url().split("/").pop();
  check(Boolean(tid), `турнир создан, открылось управление (№${tid})`);

  step("Пятеро игроков записываются");
  const token = await page.evaluate(() => localStorage.getItem("dragon_token"));
  for (let i = 1; i <= 4; i++) {
    const r = await apiCall("/auth/register", { body: { email: `p${i}-${run}@example.com`, password: "e2e-password-1", nickname: `Игрок${i}-${run}` } });
    await apiCall(`/tournaments/${tid}/register`, { token: r.access_token, method: "POST" });
  }
  await page.goto(`${BASE}/tournaments/${tid}`);
  await visible(page.getByRole("button", { name: "Записаться" }), "есть кнопка «Записаться»");
  await page.getByRole("button", { name: "Записаться" }).click();
  await page.getByText("Вы записаны").waitFor();
  check((await page.getByText("Вы записаны").count()) === 1, "сообщение «Вы записаны» показано один раз");
  await shot("registered");

  step("Старт и первый тур");
  await visible(page.getByRole("link", { name: "Управлять турниром" }), "организатор видит «Управлять турниром»");
  await page.getByRole("link", { name: "Управлять турниром" }).click();
  await page.getByRole("button", { name: "Начать турнир" }).click();
  await page.getByRole("heading", { name: "Тур 1: результаты" }).waitFor();
  const fill = async () => {
    const selects = page.locator("select[aria-label^='Результат стола']");
    await selects.first().waitFor();
    const cnt = await selects.count();
    for (let i = 0; i < cnt; i++) {
      await selects.nth(i).selectOption(i === 0 ? "p1" : "draw");
      await page.waitForTimeout(300);
    }
    return cnt;
  };
  const r1 = await fill();
  const pairs1 = await page.locator("table").first().innerText();
  await shot("round1");

  step("Следующий тур показывает новые пары, а не прошлые");
  await page.getByRole("button", { name: "Следующий тур" }).click();
  await page.getByRole("heading", { name: "Тур 2: результаты" }).waitFor();
  await page.waitForTimeout(800);
  const selects2 = page.locator("select[aria-label^='Результат стола']");
  const values = await selects2.evaluateAll((els) => els.map((e) => e.value));
  check(values.every((v) => v === ""), "результаты второго тура пустые (на экране пары второго тура)");
  const pairs2 = await page.locator("table").first().innerText();
  check(pairs1 !== pairs2, "пары второго тура отличаются от первого");
  await fill();
  await shot("round2");

  step("Завершение через подтверждение на странице");
  await page.getByRole("button", { name: "Завершить турнир" }).click();
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await page.getByText("Турнир завершён").first().waitFor();
  await page.goto(`${BASE}/tournaments/${tid}`);
  const firstH2 = await page.locator("main h2").first().innerText();
  check(firstH2 === "Таблица", "у завершённого турнира первой идёт таблица");
  const highlighted = await page.locator("tr.place-1, tr.place-2, tr.place-3").count();
  check(highlighted === 3, "три призовых места подсвечены");
  const bg = await page.locator("tr.place-2 td").first().evaluate((el) => getComputedStyle(el).backgroundColor);
  check(bg !== "rgba(255, 255, 255, 0.016)" && bg !== "rgba(0, 0, 0, 0)", `второе место подсвечено (${bg})`);
  await shot("finished");

  step("Старый клуб с кириллическим адресом открывается");
  const cyr = process.env.CYR_SLUG;
  if (cyr) {
    const resp = await page.goto(`${BASE}/clubs/${encodeURI(cyr)}`);
    check(resp.status() === 200 && !(await page.getByText("Страница не найдена").count()), `страница /clubs/${cyr} открывается`);
  } else console.log("  (пропущено: CYR_SLUG не задан)");

  step("Телефон: шапка и страница турнира");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`${BASE}/tournaments/${tid}`);
  const headerH = await page.locator("header.top").evaluate((el) => el.getBoundingClientRect().height);
  check(headerH < 130, `шапка на телефоне компактная (${Math.round(headerH)} px)`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(overflow <= 1, "нет горизонтальной прокрутки страницы");
  await shot("mobile");

  check(errors.length === 0, "в браузере нет ошибок JavaScript" + (errors.length ? ": " + errors.join("; ") : ""));
  console.log("\nГотово: путь организатора проходит в браузере.");
} catch (e) {
  await shot("FAILED").catch(() => {});
  console.error("\n" + e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
