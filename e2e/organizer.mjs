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
  await visible(page.getByText("Ваш номер игрока"), "в кабинете виден номер игрока");
  await shot("cabinet");

  step("Создание клуба с русским названием");
  await page.getByRole("link", { name: "Создать клуб" }).first().click();
  await page.getByLabel("Название").fill(`Клуб Е2Е ${run}`);
  await page.getByLabel("Город").fill("Казань");
  await page.getByRole("button", { name: "Создать клуб" }).click();
  await page.waitForURL(/\/clubs\/klub-e2e-/);
  await visible(page.getByRole("heading", { name: `Клуб Е2Е ${run}` }), "страница клуба открылась по латинскому адресу");
  await shot("club");

  const clubUrl = page.url();

  step("Мастер создания турнира: формат, настройки");
  await page.goto(BASE + "/tournaments");
  await visible(page.getByRole("link", { name: "Создать турнир" }), "на странице турниров есть «Создать турнир»");
  await page.getByRole("link", { name: "Создать турнир" }).first().click();
  await page.waitForURL(/\/tournaments\/new/);
  await page.getByText("Magic: швейцарская система").click();
  await page.getByLabel("Название", { exact: true }).fill("Е2Е швейцарка");
  await page.getByLabel("Туров", { exact: true }).fill("2");
  await page.getByLabel("Описание для игроков").fill("Приходите к **18:00**");
  const wizOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(wizOverflow <= 1, `мастер без горизонтальной прокрутки (${wizOverflow}px)`);
  await shot("wizard");
  await page.getByRole("button", { name: "Создать турнир" }).click();
  await page.waitForURL(/\/manage\/tournaments\/\d+/);
  const tid = page.url().split("/").pop();
  check(Boolean(tid), `турнир создан, открылся хаб турнира (№${tid})`);
  await visible(page.getByRole("tab", { name: /Участники/ }), "в хабе есть вкладка «Участники»");

  step("Участники: два гостя по имени и два игрока с аккаунтами");
  const addInput = page.getByLabel("Добавить игрока");
  for (const name of ["Гость Один", "Гость Два"]) {
    await addInput.fill(name);
    await page.getByRole("button", { name: "Добавить гостя" }).click();
    await visible(page.getByRole("cell", { name: new RegExp(name) }), `гость «${name}» в списке`);
  }
  {
    const r = await apiCall("/auth/register", { body: { email: `p1-${run}@example.com`, password: "e2e-password-1", nickname: `Игрок1-${run}` } });
    await apiCall(`/tournaments/${tid}/register`, { token: r.access_token, method: "POST" });
  }
  {
    // второго игрока организатор записывает по номеру игрока, как у стойки клуба
    const r = await apiCall("/auth/register", { body: { email: `p2-${run}@example.com`, password: "e2e-password-1", nickname: `Игрок2-${run}` } });
    const me = await apiCall("/auth/me", { token: r.access_token });
    check(me.player_no >= 1001, `игроку выдан номер ${me.player_no}`);
    await addInput.fill(`№${me.player_no}`);
    await visible(page.getByRole("option", { name: new RegExp(`Игрок2-${run}.*№${me.player_no}.*не из клуба`) }), "по номеру находится игрок не из клуба");
    await page.getByRole("button", { name: "Добавить", exact: true }).click();
    await visible(page.getByRole("cell", { name: new RegExp(`Игрок2-${run}.*№${me.player_no}`) }), "игрок записан по номеру, номер виден в списке");
  }
  await page.reload();
  await visible(page.getByRole("tab", { name: "Участники (4)" }), "в турнире 4 участника");
  await shot("participants");

  step("Туры: старт, ввод результатов");
  await page.getByRole("tab", { name: "Туры" }).click();
  await page.getByRole("button", { name: "Начать турнир" }).click();
  await visible(page.getByRole("button", { name: "Тур 1" }), "появился тур 1");
  const fill = async () => {
    const selects = page.locator("select[aria-label^='Результат стола']");
    await selects.first().waitFor();
    const cnt = await selects.count();
    for (let i = 0; i < cnt; i++) {
      await selects.nth(i).selectOption(i === 0 ? "p1" : "draw");
      await page.waitForTimeout(300);
    }
  };
  await fill();
  const pairs1 = await page.locator("table").first().innerText();
  await shot("round1");

  step("Следующий тур показывает новые пары; прошлый тур доступен");
  await page.getByRole("button", { name: "Следующий тур" }).click();
  await visible(page.getByRole("button", { name: "Тур 2" }), "появился тур 2");
  await page.waitForTimeout(800);
  const values = await page.locator("select[aria-label^='Результат стола']").evaluateAll((els) => els.map((e) => e.value));
  check(values.length > 0 && values.every((v) => v === ""), "результаты второго тура пустые (на экране пары второго тура)");
  check(pairs1 !== (await page.locator("table").first().innerText()), "пары второго тура отличаются от первого");
  await fill();
  await page.getByRole("button", { name: "Тур 1" }).click();
  await visible(page.getByText("Это прошлый тур"), "прошлый тур открывается для исправлений");
  await page.getByRole("button", { name: "Тур 2" }).click();
  await shot("round2");

  step("Завершение через подтверждение на странице");
  await page.getByRole("button", { name: "Завершить турнир" }).click();
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await visible(page.getByText("Турнир завершён"), "турнир завершён");
  await page.goto(`${BASE}/tournaments/${tid}`);
  check((await page.locator("main h2").first().innerText()) === "Таблица", "у завершённого турнира первой идёт таблица");
  check((await page.locator("tr.place-1, tr.place-2, tr.place-3").count()) === 3, "три призовых места подсвечены");
  const bg = await page.locator("tr.place-2 td").first().evaluate((el) => getComputedStyle(el).backgroundColor);
  check(bg.startsWith("rgba(201, 164, 76"), `второе место подсвечено (${bg})`);
  await visible(page.locator("main strong", { hasText: "18:00" }), "описание турнира показано с разметкой");
  check((await page.getByText("гость", { exact: true }).count()) === 2, "гости помечены на публичной странице");
  await shot("finished");

  step("Сезон EDH на 2 месяца");
  const clubId = await page.evaluate(async (slug) => (await (await fetch(`/api/clubs/${slug}`)).json()).id, decodeURIComponent(clubUrl.split("/clubs/")[1]));
  await page.goto(`${BASE}/manage/clubs/${clubId}`);
  await page.getByPlaceholder("Например, Осень 2026").fill("Осень E2E");
  await page.locator("form").filter({ hasText: "Новый сезон" }).getByLabel("Длительность").selectOption("2");
  await page.getByRole("button", { name: "Создать сезон" }).click();
  await visible(page.getByRole("link", { name: "Осень E2E" }), "сезон создан и виден в клубе");

  step("EDH-ивент в сезоне: мастер сам выбирает активный сезон");
  await page.goto(`${BASE}/tournaments/new?club=${clubId}`);
  await page.getByText("EDH: банк с таймером").click();
  await visible(page.getByRole("radio", { name: /Осень E2E/ }), "в мастере есть сезон");
  check(await page.getByRole("radio", { name: /Осень E2E/ }).isChecked(), "единственный активный сезон выбран сам");
  await page.getByLabel("Название", { exact: true }).fill("Е2Е EDH-среда");
  await page.getByRole("button", { name: "Создать турнир" }).click();
  await page.waitForURL(/\/manage\/tournaments\/\d+/);
  for (const name of ["Аня", "Боря", "Вася"]) {
    await page.getByLabel("Добавить игрока").fill(`${name} ${run}`);
    await page.getByRole("button", { name: "Добавить гостя" }).click();
    await visible(page.getByRole("checkbox", { name: `${name} ${run} пришёл` }), `${name} добавлен`);
    await page.getByRole("checkbox", { name: `${name} ${run} пришёл` }).check();
    await page.waitForTimeout(400);
  }
  await page.getByRole("tab", { name: "Столы" }).click();
  await page.getByRole("button", { name: "Рассадить и начать" }).click();
  await visible(page.getByText("осталось 70 мин"), "стол с таймером 70 минут");
  await page.locator("select[aria-label^='Победитель стола']").first().selectOption({ label: `Аня ${run}` });
  await page.getByRole("button", { name: "Записать победу" }).click();
  await visible(page.getByText("Аня " + run + ", победитель"), "победитель отмечен за столом");
  await page.getByRole("button", { name: "Завершить ивент" }).click();
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await visible(page.getByText("Ивент завершён"), "ивент завершён");
  await shot("edh");

  step("Таблица сезона: банк сезона с 1000");
  await page.getByRole("link", { name: "Осень E2E" }).click();
  await page.waitForURL(/\/leagues\/\d+/);
  const seasonRows = await page.locator("table tbody tr").allInnerTexts();
  check(seasonRows.length === 3, "в таблице сезона трое");
  check(seasonRows[0].includes(`Аня ${run}`) && /1\s?311/.test(seasonRows[0]), `лидер сезона Аня с банком 1311 (${seasonRows[0].replace(/\s+/g, " ")})`);
  await shot("season");

  step("Старый клуб с кириллическим адресом открывается");
  const cyr = process.env.CYR_SLUG;
  if (cyr) {
    const resp = await page.goto(`${BASE}/clubs/${encodeURI(cyr)}`);
    check(resp.status() === 200 && !(await page.getByText("Страница не найдена").count()), `страница /clubs/${cyr} открывается`);
  } else console.log("  (пропущено: CYR_SLUG не задан)");

  step("Судья клуба: назначение по номеру и ведение турнира");
  {
    const orgToken = await page.evaluate(() => localStorage.getItem("dragon_token"));
    const club = (await apiCall("/clubs/managed", { token: orgToken })).find((c) => c.name === `Клуб Е2Е ${run}`);
    const jr = await apiCall("/auth/register", { body: { email: `judge-${run}@example.com`, password: "e2e-password-1", nickname: `Судья-${run}` } });
    const judgeMe = await apiCall("/auth/me", { token: jr.access_token });
    await page.goto(`${BASE}/manage/clubs/${club.id}`);
    await page.getByLabel("Номер игрока").fill(String(judgeMe.player_no));
    await page.getByRole("button", { name: "Назначить судьёй" }).click();
    await visible(page.getByText("Судья назначен"), "организатор назначил судью по номеру");
    await visible(page.getByRole("link", { name: `Судья-${run}` }), "судья виден в списке судей клуба");
    await shot("judges");
    const t2 = await apiCall("/tournaments", { token: orgToken, body: { club_id: club.id, name: "Е2Е с судьёй", format: "swiss", rounds: 1 } });
    const jp = await browser.newPage({ viewport: { width: 1200, height: 900 } });
    jp.on("pageerror", (e) => errors.push(e.message));
    await jp.goto(BASE + "/");
    await jp.evaluate((tok) => localStorage.setItem("dragon_token", tok), jr.access_token);
    await jp.goto(`${BASE}/tournaments/${t2.id}`);
    await jp.getByRole("link", { name: "Управлять турниром" }).click();
    await jp.waitForURL(/\/manage\/tournaments\/\d+/);
    await visible(jp.getByRole("tab", { name: /Участники/ }), "судья открыл хаб турнира");
    check(await jp.getByRole("tab", { name: "Настройки" }).count() === 0, "вкладки «Настройки» у судьи нет");
    await jp.getByLabel("Добавить игрока").fill("Гость судьи");
    await jp.getByRole("button", { name: "Добавить гостя" }).click();
    await visible(jp.getByRole("cell", { name: /Гость судьи/ }), "судья записал игрока");
    await jp.close();
    await page.goto(`${BASE}/manage/tournaments/${t2.id}`);
    await page.getByLabel(/Главный судья/).selectOption({ label: `Судья-${run}` });
    let card = null;
    for (let i = 0; i < 20 && card?.judge?.nickname !== `Судья-${run}`; i++) {
      await page.waitForTimeout(250);
      card = await apiCall(`/tournaments/${t2.id}`);
    }
    check(card.judge?.nickname === `Судья-${run}`, "организатор назначил главного судью");
  }

  step("Пароль: смена в кабинете, вход и «Забыли пароль?»");
  await page.goto(BASE + "/me");
  await page.getByRole("button", { name: "Сменить пароль" }).click();
  await page.getByLabel("Текущий пароль").fill("e2e-password-1");
  await page.getByLabel("Новый, не короче 8 символов").fill("e2e-password-2");
  await page.getByLabel("Повторите новый").fill("e2e-password-2");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await visible(page.getByText("Пароль изменён"), "пароль сменился, кабинет остался открыт");
  await page.reload();
  await visible(page.getByRole("heading", { name: "Мои клубы" }), "после перезагрузки вход не слетел (новый токен)");
  const guest = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  guest.on("pageerror", (e) => errors.push(e.message));
  await guest.goto(BASE + "/login");
  await guest.getByLabel("Email").fill(`org-${run}@example.com`);
  await guest.getByLabel("Пароль").fill("e2e-password-1");
  await guest.getByRole("button", { name: "Войти", exact: true }).click();
  await visible(guest.getByText("Неверный email или пароль"), "старый пароль не подходит");
  await guest.getByRole("link", { name: "Забыли пароль?" }).click();
  await guest.waitForURL("**/forgot");
  check(await guest.getByLabel("Email").inputValue() === `org-${run}@example.com`, "email перенесён со страницы входа");
  await guest.getByRole("button", { name: "Прислать ссылку" }).click();
  await visible(guest.getByRole("heading", { name: "Проверьте почту" }), "запрос ссылки принят");
  await guest.goto(BASE + "/login");
  await guest.getByLabel("Email").fill(`org-${run}@example.com`);
  await guest.getByLabel("Пароль").fill("e2e-password-2");
  await guest.getByRole("button", { name: "Войти", exact: true }).click();
  await guest.waitForURL("**/me");
  console.log("  ✓ вход с новым паролем");
  await guest.goto(BASE + "/reset?token=not-a-real-token-1234567890");
  await guest.getByLabel("Новый пароль, не короче 8 символов").fill("e2e-password-3");
  await guest.getByLabel("Повторите пароль").fill("e2e-password-3");
  await guest.getByRole("button", { name: "Сохранить и войти" }).click();
  await visible(guest.getByText("Ссылка устарела или уже использована"), "поддельная ссылка сброса отклонена");
  check(new URL(guest.url()).search === "", "токен убран из адресной строки");
  await guest.close();

  step("Телефон: шапка и страница турнира");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`${BASE}/tournaments/${tid}`);
  const headerH = await page.locator("header.top").evaluate((el) => el.getBoundingClientRect().height);
  check(headerH < 130, `шапка на телефоне компактная (${Math.round(headerH)} px)`);
  await page.setViewportSize({ width: 820, height: 900 });
  const navLines = await page.locator("nav.nav a").evaluateAll((els) => new Set(els.map((e) => Math.round(e.getBoundingClientRect().top))).size);
  check(navLines === 1, `меню на ширине 820px в одну строку (строк: ${navLines})`);
  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(() => {
    const extra = document.documentElement.scrollWidth - window.innerWidth;
    const wide = [...document.querySelectorAll("main *")].filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
      .filter((el) => !el.closest(".table-wrap") || el.classList.contains("table-wrap")).slice(0, 3)
      .map((el) => `${el.tagName.toLowerCase()}.${el.className}`);
    return { extra, wide };
  });
  check(overflow.extra <= 1, "нет горизонтальной прокрутки страницы" + (overflow.extra > 1 ? ` (лишние ${overflow.extra}px: ${overflow.wide.join(", ")})` : ""));
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
