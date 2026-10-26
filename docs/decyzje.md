# Dziennik decyzji

Decyzje podjęte w trakcie budowy, od najnowszej. Decyzje klienta z planu wdrożenia (1–16) są w dokumencie „Plan wdrożenia fdsrun-v2” i tu się do nich odwołuję.

## 2026-10-26 — Etap 0

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
