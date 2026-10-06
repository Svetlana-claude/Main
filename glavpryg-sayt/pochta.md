# Почта Главпрыга — glavpryg@mokeevasky.ru

Ящик заведён 06.10.2026 на нашем сервере (`mokeevasky.ru`, 46.8.178.196).
На него приходят копии сертификатов и заявки сайта, с него сайт пишет
покупателям. Прежний `info@glavpryg.ru` не используется: DNS домена
`glavpryg.ru` (Lealhost) не отвечает.

## Что работает уже сейчас

- Ящик принимает и хранит письма, вход по IMAP — проверено.
- Сайт отправляет письма через этот сервер: покупателю — сертификат, в ящик —
  копию с данными заказа. Письма подписываются DKIM.
- «E-mail администрации» в настройках сайта — `glavpryg@mokeevasky.ru`.

## Что нужно сделать в Cloudflare (DNS домена mokeevasky.ru)

Без этих записей письма извне в ящик не придут, а письма покупателям Gmail,
Яндекс и Mail.ru отвергнут или положат в спам.

| Тип | Имя | Значение | Приоритет |
|---|---|---|---|
| MX | `@` (mokeevasky.ru) | `mokeevasky.ru` | 10 |
| TXT | `@` | `v=spf1 ip4:46.8.178.196 mx ~all` | — |
| TXT | `mail._domainkey` | см. ниже | — |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:glavpryg@mokeevasky.ru` | — |

Значение записи `mail._domainkey` — одной строкой:

```
v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAykfd0+C2prp11RpGOzVN32opzzfF9cm1BDxY9PwHZ7+7wsUlz7YjlTYST4MP2cnOOyXtvPdZOAGSUWHsi0sL8p06OkzlIyIUEi0j54gIaPYVqZ2AG1D71XNsHC8wbQ7GOBcWT8CPC3F+S2DdjuMESL188m/8irdIc9CKFxmgg/c9fXTxUsdPC2V1jVlFm4FovhCKiPuqBLdRL52iLmXxJjQ2b8CDmfyjHplY3ituV2YcKsC1xHkohhw6tLDGjF+SdI7xF7kjt7oL+DIvMNwFSPfxT4FI5R+ImawX0yjlE0aBjnZcKh/bOndFtndGSNxzabYx3vVMfSSDzAR7rGo+eQIDAQAB
```

Запись `A` для `mokeevasky.ru` должна оставаться «DNS only» (серое облако) —
через прокси Cloudflare почта не ходит. Сейчас так и есть.

Вместо ручного ввода можно дать API-токен Cloudflare с правом «Zone → DNS →
Edit» на зону `mokeevasky.ru` — записи заведём сами.

## Что нужно сделать у хостера (FirstByte)

Обратная запись **PTR** для IP `46.8.178.196` → `mokeevasky.ru`. Делается в
панели FirstByte или письмом в поддержку. Без неё Gmail письма не принимает.

## Как войти в ящик из почтовой программы

| | Сервер | Порт | Защита |
|---|---|---|---|
| Входящая (IMAP) | `mokeevasky.ru` | 993 | SSL/TLS |
| Исходящая (SMTP) | `mokeevasky.ru` | 587 | STARTTLS |

Логин — `glavpryg@mokeevasky.ru`, пароль хранится на сервере в
`~/.config/glavpryg-mail.pass` (в git не попадает), выдаётся по запросу.
