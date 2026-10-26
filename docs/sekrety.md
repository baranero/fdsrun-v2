# Sekrety i zmienne w GitHubie

Wszystkie klucze trzymasz w repozytorium: **Settings → Secrets and variables → Actions**.
Ja ich nie widzę; używają ich tylko workflow na GitHubie i serwer.

## Sekrety (zakładka *Secrets*)

| Nazwa | Skąd | Kiedy potrzebny |
| --- | --- | --- |
| `HCLOUD_TOKEN` | Hetzner Cloud → projekt fdsrun-v2 → Security → API tokens (Read & Write) | od etapu 0 (jest) |
| `STRIPE_SECRET_KEY` | Stripe → Developers → API keys (na start klucz testowy `sk_test_…`) | etap 3 |
| `STRIPE_WEBHOOK_SECRET` | Stripe → Developers → Webhooks | etap 3 |
| `ING_API_KEY` | ING Księgowość → Dane i ustawienia → Integracje → Klucz API | etap 3 |
| `EMAIL_API_KEY` | dostawca poczty (podam, który) | etap 2 |

## Zmienne (zakładka *Variables*)

| Nazwa | Wartość | Kiedy |
| --- | --- | --- |
| `STAGING_DOMAIN` | `staging.fdsrun.com` — ustaw dopiero, gdy rekord DNS wskazuje na serwer | po etapie 0 |

## Jak powstaje serwer

1. Workflow **Provision portal server** (Actions → uruchom ręcznie) tworzy serwer z firewallem (tylko porty 80 i 443) i wpisuje do niego `HCLOUD_TOKEN` oraz wygenerowane hasła bazy i klucz Django.
2. Workflow **CI and deploy** przy każdym pushu na `main` buduje obraz i wysyła go na serwer.
3. Dopóki nie ma DNS, serwer odpowiada pod `https://<ip>.sslip.io`.

Serwer nie ma SSH. Logi i stan odczytuję przez podpisany endpoint `/_deploy/status`.
