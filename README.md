# fdsrun-v2

Portal do obliczeń FDS w chmurze — nowa wersja fdsrun.com, budowana od zera.
Specyfikacja projektu: dokument „Portal obliczeń FDS – specyfikacja projektu” w Claude.

## Etap 1: analizator plików .fds

`analyzer/fds-analyzer.js` — jeden plik, działa w przeglądarce i w Node:

- czyta grupy namelist (`&MESH`, `&TIME`, `&OBST`, `&SURF`, `&DEVC`, `&HVAC`…),
- sprawdza typowe błędy: brak `&TAIL`, urządzenia poza siatkami, odwołania do niezdefiniowanych SURF/RAMP/DEVC, nachodzące siatki, złe proporcje komórek, kolejność `MPI_PROCESS`, temperatury przegród, brak `DT_RESTART`,
- liczy obciążenie procesów MPI i doradza liczbę procesów oraz serwer,
- szacuje czas i koszt: `czas = k × komórki_najwolniejszego_procesu × kroki`, gdzie `kroki = T_END × u / (0,9 × Δx_min)`, a `u` to prędkość z pióropusza pożaru i wymuszonych przepływów.

Współczynnik `k = 2,1 µs` skalibrowano na 6 zleceniach klatek schodowych z września 2026 (błąd ±40%). Modele z HVAC/wentylacją strumieniową liczą się 2–10× dłużej — dla nich wycenę daje dopiero bieg testowy.

### Polecenia

Pliki .fds i eksport CSV ze starego portalu trzymamy poza repozytorium (katalog `samples/`, ignorowany przez git).

```bash
node analyzer/calibrate.js samples               # porównanie szacunków z rzeczywistymi czasami
node analyzer/build.js samples analyzer-fds.html # strona analizatora z wbudowanymi przykładami
```
