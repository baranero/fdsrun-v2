# fdsrun-v2

Portal do obliczeń FDS w chmurze — nowa wersja fdsrun.com, budowana od zera.
Specyfikacja projektu: dokument „Portal obliczeń FDS – specyfikacja projektu” w Claude.

## Etap 1: analizator plików .fds

`analyzer/fds-analyzer.js` — jeden plik, działa w przeglądarce i w Node:

- czyta grupy namelist (`&MESH`, `&TIME`, `&OBST`, `&SURF`, `&DEVC`, `&HVAC`…),
- sprawdza typowe błędy: brak `&TAIL`, urządzenia poza siatkami, odwołania do niezdefiniowanych SURF/RAMP/DEVC, nachodzące siatki, złe proporcje komórek, kolejność `MPI_PROCESS`, temperatury przegród, brak `DT_RESTART`,
- liczy obciążenie procesów MPI i doradza liczbę procesów oraz serwer,
- szacuje czas i koszt: `czas = k(serwer) × komórki_najwolniejszego_procesu × kroki`, gdzie `kroki = ∫u(t)dt / (0,9 × Δx_min)`.
  Prędkość `u(t)` to największa z: pióropusz pożaru (wg RAMP_Q), efekt kominowy (&INIT vs TMPA), wentylacja mechaniczna (z chwilą włączenia wg DEVC), ruch resztkowy 2,2 m/s.

Kalibracja na plikach .out z września 2026 (FDS 6.10.1): liczba kroków ±6% na klatkach, +3–4% na garażu;
czas liczenia ±15%. `k` = 3,4 µs na cpx42 i 5,3 µs na cpx62. Wentylację mechaniczną skalibrowano na jednym garażu.

### Polecenia

Pliki .fds, .out i eksport CSV ze starego portalu trzymamy poza repozytorium (katalogi `samples/` i `out/`, ignorowane przez git).

```bash
node analyzer/parse-out.js out                        # statystyki z plików .out
node analyzer/calibrate.js samples out                # szacunek kontra rzeczywistość
node analyzer/build.js samples analyzer-fds.html out  # strona analizatora z wbudowanymi przykładami
```
