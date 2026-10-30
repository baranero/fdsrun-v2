# Dziennik decyzji

Decyzje podjęte w trakcie budowy, od najnowszej. Decyzje klienta z planu wdrożenia (1–16) są w dokumencie „Plan wdrożenia fdsrun-v2” i tu się do nich odwołuję.

## 2026-10-26 — Etap 0

**D-12. Awaria portalu nie może zabić obliczeń (incydent 29/30.10.2026).**
Osiem równoległych zleceń i dublujące je archiwa ZIP zapełniły dysk portalu; baza danych stanęła, portal przestał przyjmować sygnały od maszyn, a strażnik usunął żywą maszynę po 10 minutach ciszy. Zmiany: (1) strażnik przed przerwaniem pyta Hetznera, czy serwer działa — działający serwer bez sygnału jest zostawiany do 6 h, z alarmem do admina; (2) automatycznie powstaje tylko małe archiwum „CSV i logi”, duże tylko na żądanie, gdy jest miejsce (rezerwa 5 GB), i znikają po 48 h; (3) zlecenie przerwane z winy infrastruktury (brak odpowiedzi) jest bezpłatne; (4) przerwane zlecenie z plikami restartu można wznowić — wyniki są przenoszone do wznowienia, FDS startuje z RESTART=.TRUE.; (5) pliki restartu są wysyłane w całości po każdym zapisie (wcześniej nadpisanie o tym samym rozmiarze nie było wykrywane); (6) awaryjne „free-space” i raport dysku w panelu wdrożeń.

**D-11. Rozliczenia (decyzje klienta 29.10.2026).**
Wyniki są do pobrania od razu po obliczeniach, bez czekania na zapłatę. Faktura przychodzi e-mailem; klient płaci dowolną metodą udostępnioną przez Stripe (karta, BLIK, Przelewy24, portfele) albo zwykłym przelewem na konto firmy. Firmy wybierają fakturę po każdym zleceniu albo zbiorczą za miesiąc (wystawianą 1. dnia następnego miesiąca); termin płatności 14 dni. Nowe konto ma limit nieopłaconego salda 500 zł do pierwszej zapłaconej faktury; zaufane konta bez limitu. Faktura po terminie blokuje uruchamianie nowych zleceń, nie pobieranie. Weryfikacja karty przed pierwszym zleceniem nie jest obowiązkowa. Stawka studencka po weryfikacji domeny uczelni albo przez administratora. Na stagingu faktury powstają jako projekty; do ING (KSeF) trafiają dopiero po ręcznym „Wystaw w ING” w panelu.

**D-10. Pliki wyników serwuje Caddy, nie Django.**
Ścieżka `/pobierz/<id>/<plik>` trafia do Caddy, który pyta Django (`forward_auth` → `/api/download/auth`), czy wolno, i sam strumieniuje plik z wolumenu `jobdata` z obsługą HTTP Range. Dzięki temu 10-GB archiwum nie blokuje procesu gunicorna, a pobieranie da się wznowić (`curl -C -`, menedżery pobierania). Linki tymczasowe: HMAC z datą ważności (7 dni), bez logowania. Archiwa ZIP bez kompresji budowane po zakończeniu zlecenia (task `build_archives_task`).

**D-9. Kontener FDS startuje z `--ipc=host` i nielimitowanym stosem (`ulimit -s unlimited`).**
Docker domyślnie daje kontenerowi 64 MB `/dev/shm` i 8 MB stosu. Intel MPI wymienia dane między procesami przez `/dev/shm`, a FDS (kompilator Intel) trzyma duże tablice na stosie — przy 8 procesach na cpx42 klatkaD padała po kilkunastu krokach z sygnałem „Bus error” (znalezione 27.10 przez powtórzenie zlecenia 6E38B092 z diagnostyką). Skrypty uruchomieniowe NIST same ustawiają `ulimit -s unlimited`. Po zmianie klatkaD liczy się na 8 procesach.

**D-8. Przekroczenie wyceny nie zatrzymuje obliczeń.** Decyzja klienta: gdy prognoza przekracza wycenę o ponad 30%, portal tylko informuje w statusie zlecenia; obliczenia biegną dalej, a cena rośnie proporcjonalnie. Mechanizm pauzy zostaje w kodzie wyłączony.

**D-7. Wdrażanie bez SSH: „deployer” na serwerze przyjmuje podpisane aktualizacje z GitHub Actions.**
Warsztat, w którym piszę kod, nie ma dostępu do Hetznera, a klucz SSH wymagałby kolejnego sekretu. Zamiast tego na serwerze działa mały serwis (`deploy/deployer/deployer.py`), do którego GitHub Actions wysyła przez HTTPS podpisany pakiet: nazwę obrazu, pliki `compose.yml` i `Caddyfile`, tymczasowy token do rejestru obrazów. Podpis to HMAC z klucza wyprowadzonego z `HCLOUD_TOKEN`, który obie strony i tak znają. Żądania starsze niż 5 minut są odrzucane. Na serwerze nie ma w ogóle otwartego portu SSH (firewall: tylko 80 i 443).

**D-6. Jeden obraz Docker dla web, workera i beat.** Prostsze wdrożenie, jedna wersja kodu wszędzie.

**D-5. Pliki zleceń na dysku serwera portalu (wolumen Docker), nie w Object Storage.**
W etapie 1 upraszcza to start (jeden sekret mniej). Warstwa plików w `apps/jobs/models.py` jest w jednym miejscu, więc przejście na Hetzner Object Storage (S3) to wymiana jednej klasy. Decyzja do rewizji, gdy wyniki przekroczą ~20 GB.

**D-4. Agent na maszynie obliczeniowej rozmawia wyłącznie z portalem, przez HTTPS, tokenem jednorazowym dla zlecenia.**
Maszyna nie dostaje żadnych kluczy do chmury. Token podróżuje w cloud-init i działa tylko dla jednego zlecenia; po zakończeniu portal odrzuca go. Agent (`compute/agent.py`) to jeden plik w czystym Pythonie, bez bibliotek.

**D-3. „Bieg testowy” to pierwsze 2 minuty prawdziwych obliczeń, nie osobne uruchomienie.**
Jeśli FDS padnie w tym oknie, zlecenie kończy się ze statusem błędu biegu testowego; jeśli nie, te 2 minuty liczą się do wyniku. Nie marnujemy czasu maszyny i nie potrzebujemy drugiego startu.

**D-2. Obraz FDS budowany z oficjalnej paczki NIST (FDS 6.10.1 + Intel MPI), publiczny na ghcr.io.**
Obraz zawiera tylko otwarte oprogramowanie NIST, więc może być publiczny — maszyny obliczeniowe pobierają go bez haseł. Wersja FDS taka sama jak w plikach .out klienta z września 2026.

**D-1. Jeden analizator plików .fds (JavaScript) dla przeglądarki i serwera.**
Portal uruchamia `analyzer/cli.js` przez Node w kontenerze zamiast utrzymywać drugą implementację w Pythonie. Kalibracja i walidacja są w jednym miejscu.
