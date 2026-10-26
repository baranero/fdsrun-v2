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
- [ ] Serwer staging utworzony, deployer odpowiada
- [ ] Pierwsze wdrożenie przeszło, https://<ip>.sslip.io/healthz = ok
- [ ] Bramka: mały model testowy policzony na maszynie obliczeniowej od A do Z

## Etap 1 — silnik obliczeń
- [x] Tworzenie maszyny przez API Hetzner, cloud-init z agentem
- [x] Agent: pobranie modelu, FDS pod MPI, postęp co 10 s, pliki co 60 s, zakończenie
- [x] Zatrzymanie przez użytkownika (plik CHID.stop, limit 5 min)
- [x] Watchdog: brak sygnału → zlecenie „brak odpowiedzi”, maszyna usunięta; zapomniane maszyny usuwane
- [ ] Alarm e-mail/SMS do admina o zapomnianej maszynie (po etapie 2, gdy będzie poczta)
- [ ] Pauza i potwierdzenie przy przekroczeniu wyceny o 30%
- [ ] Przeliczanie szacunku z rzeczywistego tempa (ETA już jest; kalibracja współczynnika k z każdego zlecenia)
- [ ] Bramka: klatkaD liczy się od wysłania pliku do pobrania wyników

## Etap 2 — konta i zlecenia
- [ ] 2FA (aplikacja), reset hasła, potwierdzenie e-maila
- [ ] Wykresy HRR/DEVC na żywo z plików CSV
- [ ] Obrazki przekrojów (slice)
- [ ] Poczta transakcyjna (dostawca w UE)
- [ ] Bramka: 3 modele klienta policzone przez portal — akceptacja klienta

## Etap 3 — pieniądze
- [ ] Dane do faktury, weryfikacja NIP (GUS) i VAT UE (VIES)
- [ ] Stripe: weryfikacja karty, obciążenie po obliczeniach, BLIK, P24
- [ ] Faktury PL/EN przez ING Księgowość (KSeF); plan B uzgodnić z klientem
- [ ] Przypomnienia, blokada konta, wezwanie do zapłaty
- [ ] Opłata minimalna i mnożniki wg decyzji 5–6

## Etap 4 — panel admina
- [ ] Pulpit: zlecenia, przychód, koszty, marża, maszyny
- [ ] Dziennik dostępu admina do plików klientów (zapis jest, brak widoku)
- [ ] Projekty regulaminu, polityki prywatności, DPA

## Etap 5 — angielski, testy, Smokeview w przeglądarce
## Etap 6 — start
