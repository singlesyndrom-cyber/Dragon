# Dragon для Android (RuStore)

Приложение — Trusted Web Activity: сайт dragonclub.games на весь экран, без адресной строки, с иконкой клуба.
Стартовая страница — «За столом» (`/play`). Если на телефоне нет Chrome (или браузер не умеет TWA),
открывается встроенный WebView. Обновлять APK при изменениях сайта не нужно.

## Ключ подписи (один раз)

На сервере (пароль придумайте сами и сохраните; без ключа нельзя будет обновить приложение в RuStore):

```
mkdir -p /opt/dragon-keys && cd /opt/dragon-keys
docker run --rm -it -v /opt/dragon-keys:/k eclipse-temurin:17-jdk keytool -genkeypair -v \
  -keystore /k/dragon.jks -alias dragon -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=Dragon, O=Dragon club, C=RU"
base64 -w0 dragon.jks > dragon.jks.b64
```

Сделайте копию `dragon.jks` в надёжное место (не в репозиторий!).

Секреты репозитория (GitHub → Settings → Secrets and variables → Actions → New repository secret):

| Секрет | Значение |
|---|---|
| `ANDROID_KEYSTORE_B64` | содержимое `dragon.jks.b64` |
| `ANDROID_KEYSTORE_PASSWORD` | пароль хранилища |
| `ANDROID_KEY_ALIAS` | `dragon` |
| `ANDROID_KEY_PASSWORD` | пароль ключа (по умолчанию тот же) |

## Сборка

GitHub → Actions → **Android** → Run workflow. В итогах сборки:
- архив `dragon-android-N` с `dragon.apk` и `dragon.aab` — для загрузки в RuStore;
- строка `ANDROID_CERT_SHA256=…` — добавьте её в `.env` на сервере и перезапустите сайт.
  Тогда https://dragonclub.games/.well-known/assetlinks.json подтвердит связь, и адресная строка исчезнет.

С галочкой «Выложить APK в Releases» файл появится по постоянной ссылке
https://github.com/singlesyndrom-cyber/Dragon/releases/latest/download/dragon.apk (кнопка «Скачать» на сайте).
