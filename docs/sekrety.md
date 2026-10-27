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
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Brevo (brevo.com, serwery w UE, 300 maili dziennie za darmo): SMTP & API → klucze SMTP. Host `smtp-relay.brevo.com`, port `587`, login = e-mail konta Brevo, hasło = klucz SMTP | etap 2 |
| `DEFAULT_FROM_EMAIL` | np. `fdsrun <noreply@fdsrun.com>` — nadawcę trzeba potwierdzić w Brevo (Senders) | etap 2 |
| `ADMIN_EMAIL` | adres na alarmy o maszynach, np. `biuro@fp-solutions.pl` | etap 2 |
| `COMPANY_NAME`, `COMPANY_ADDRESS`, `COMPANY_NIP`, `COMPANY_EMAIL` | dane firmy do regulaminu, polityki prywatności i faktur (domyślne z CEIDG są w kodzie; sekret nadpisuje) | przed etapem 3 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | logowanie przez Google — instrukcja niżej | etap 2 |
| `GH_OAUTH_CLIENT_ID`, `GH_OAUTH_CLIENT_SECRET` | logowanie przez GitHub — instrukcja niżej | etap 2 |
| `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | logowanie przez Microsoft — instrukcja niżej | etap 2 |

## Logowanie przez Google, GitHub, Microsoft

Przycisk pojawia się na stronie logowania tylko dla dostawcy, którego klucze są wpisane. Każda aplikacja OAuth wymaga dwóch adresów zwrotnych — jednego dla staging, jednego dla produkcji:

- `https://staging.fdsrun.com/konto/zewnetrzne/google/login/callback/`, `…/github/login/callback/`, `…/microsoft/login/callback/`
- `https://fdsrun.com/konto/zewnetrzne/google/login/callback/` itd. (dodasz przy starcie produkcji)

**Google** — console.cloud.google.com → projekt (np. „fdsrun”) → *APIs & Services → OAuth consent screen*: typ External, nazwa „fdsrun”, e-mail wsparcia biuro@fp-solutions.pl, domena `fdsrun.com`; publish (bez weryfikacji wystarczy do zakresów e-mail/profil). Potem *Credentials → Create credentials → OAuth client ID → Web application*: Authorized redirect URIs = adresy wyżej. Dostaniesz Client ID i Client secret → sekrety `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

**GitHub** — github.com → Settings → Developer settings → OAuth Apps → New OAuth App: nazwa „fdsrun”, Homepage `https://fdsrun.com`, Authorization callback URL = adres staging (GitHub pozwala na jeden adres na aplikację — dla produkcji załóż drugą aplikację albo zmień adres przy starcie). *Generate a new client secret* → sekrety `GH_OAUTH_CLIENT_ID`, `GH_OAUTH_CLIENT_SECRET` (nazwy inne niż `GITHUB_*`, bo GitHub rezerwuje ten prefiks).

**Microsoft** — entra.microsoft.com (lub portal.azure.com) → *App registrations → New registration*: nazwa „fdsrun”, *Supported account types*: „Accounts in any organizational directory and personal Microsoft accounts”, Redirect URI (Web) = adresy wyżej. Z *Overview* weź *Application (client) ID* → `MS_CLIENT_ID`; *Certificates & secrets → New client secret* (24 miesiące) → wartość → `MS_CLIENT_SECRET`.

Po wpisaniu sekretów wystarczy ponowne wdrożenie (dowolny push albo *Re-run* ostatniego „CI and deploy”).

## Domena

Wdrożenie samo sprawdza, czy `staging.fdsrun.com` wskazuje na serwer (rekord A w DNS, u Vercela). Dopóki nie wskazuje, portal działa pod `https://<ip>.sslip.io`; gdy wskazuje, przepina się na domenę przy następnym wdrożeniu.

## Jak powstaje serwer

1. Workflow **Provision portal server** (Actions → uruchom ręcznie) tworzy serwer z firewallem (tylko porty 80 i 443) i wpisuje do niego `HCLOUD_TOKEN` oraz wygenerowane hasła bazy i klucz Django.
2. Workflow **CI and deploy** przy każdym pushu na `main` buduje obraz i wysyła go na serwer.
3. Dopóki nie ma DNS, serwer odpowiada pod `https://<ip>.sslip.io`.

Serwer nie ma SSH. Logi i stan odczytuję przez podpisany endpoint `/_deploy/status`.
