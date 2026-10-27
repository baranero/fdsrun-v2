# Plan zadań

Stan prac po etapach. Pełny plan z bramkami: dokument „Plan wdrożenia fdsrun-v2”.
Nowa sesja zaczyna od tego pliku: pierwsze niezrobione zadanie to następny krok.

## Etap 0 — przygotowanie
- [x] Analizator .fds skalibrowany na plikach .out (±15%)
- [x] Szkielet Django: konta, zlecenia, obliczenia; testy przechodzą
- [x] Obraz FDS 6.10.1 (`fds-image/`) i workflow budujący go do ghcr.io
- [x] Obraz portalu, compose, Caddy, deployer, cloud-init serwera
- [x] Workflow CI → build → deploy-staging
- [x] Workflow provision (tworzy serwer portalu z firewallem)
- [x] Serwer staging utworzony, deployer odpowiada (adres w issue „Adresy środowisk”)
- [x] Pierwsze wdrożenie przeszło, /healthz = ok
- [x] Bramka: mały model testowy policzony na maszynie obliczeniowej od A do Z (workflow *Smoke test*, 26.10, 1 min 43 s, 0,002 €)

## Etap 1 — silnik obliczeń
- [x] Tworzenie maszyny przez API Hetzner, cloud-init z agentem
- [x] Agent: pobranie modelu, FDS pod MPI, postęp co 10 s, pliki co 60 s, zakończenie
- [x] Zatrzymanie przez użytkownika (plik CHID.stop, limit 5 min)
- [x] Watchdog: brak sygnału → zlecenie „brak odpowiedzi”, maszyna usunięta; zapomniane maszyny usuwane
- [x] Alarm e-mail do admina o zapomnianej/nieusuwalnej maszynie i zleceniu bez odpowiedzi
- [x] Przekroczenie wyceny o 30%: tylko informacja w statusie (decyzja klienta D-8), bez zatrzymywania
- [x] Przeliczanie szacunku z rzeczywistego tempa (ETA) i kalibracja k z każdego zakończonego zlecenia
- [x] Konto admina klienta (biuro@fp-solutions.pl)
- [x] Błąd „Bus error” przy 8 procesach (klatkaD) naprawiony: `--ipc=host` + nielimitowany stos (D-9); komendy admina `job_retry`, `job_stop`, smoke test z `copy_of`/`stop_after_s`
- [ ] Bramka: klatkaD liczy się od wysłania pliku do pobrania wyników (ponowny start 27.10 przez `job_retry`)

## Etap 2 — konta i zlecenia
- [x] Nowy wygląd (27.10): pasek menu, paleta, tryb ciemny, responsywność; pulpit, lista z filtrami, ekran zlecenia z zakładkami, konsola FDS na żywo, strona główna i cennik/FAQ (dokument „analiza UX i plan nowego interfejsu”)
- [x] Pobieranie: archiwa CSV/Smokeview/wszystko po zakończeniu, Caddy serwuje pliki z HTTP Range (wznawianie), linki podpisane na 7 dni bez logowania, `curl -C -`/`wget -c`
- [ ] Foldery projektów; logowanie Google/GitHub/Microsoft; dane do faktury w koncie
- [x] Reset hasła, potwierdzenie e-maila (wymagane przed startem obliczeń)
- [x] 2FA (aplikacja TOTP, kody zapasowe)
- [x] Wykresy HRR/DEVC na żywo z plików CSV
- [ ] Obrazki przekrojów (slice)
- [x] Poczta: SMTP przez Brevo (klucze do wpisania w GitHub — docs/sekrety.md); do tego czasu maile idą do logu
- [x] Powiadomienia e-mail o zakończeniu/błędzie zlecenia
- [ ] Bramka: 3 modele klienta policzone przez portal — akceptacja klienta

## Etap 3 — pieniądze
- [ ] Dane do faktury, weryfikacja NIP (GUS) i VAT UE (VIES)
- [ ] Stripe: weryfikacja karty, obciążenie po obliczeniach, BLIK, P24
- [ ] Faktury PL/EN przez ING Księgowość (KSeF); plan B uzgodnić z klientem
- [ ] Przypomnienia, blokada konta, wezwanie do zapłaty
- [ ] Opłata minimalna i mnożniki wg decyzji 5–6

## Etap 4 — panel admina
- [x] Pulpit: zlecenia, przychód, koszty, marża, maszyny, trafność wycen, kalibracja (`/panel/`)
- [x] Użytkownicy: rodzaj konta, zaufany, limit, blokada; maszyny z ręcznym usuwaniem
- [x] Dziennik dostępu admina do plików klientów
- [x] Cena rzeczywista zlecenia = koszt serwera × mnożnik (zapisywana po usunięciu maszyny)
- [x] Projekty regulaminu, polityki prywatności, cookies i DPA (`/regulamin/` itd.) — do sprawdzenia przez prawnika; dane firmy (adres, NIP) do uzupełnienia w sekretach COMPANY_*

## Etap 5 — angielski, testy, Smokeview w przeglądarce
## Etap 6 — start
