# Faktury, VAT i ING Księgowość — ustalenia (27.10.2026)

Research na podstawie stron ING i poradników podatkowych; **do potwierdzenia z księgową/doradcą** przed startem sprzedaży.
Usługodawca: Fire Protection Solutions Jakub Baran, JDG, siedziba w Polsce (CEIDG, NIP 6182094888).

## ING Księgowość — API
- Endpointy: `POST https://ksiegowosc.ing.pl/v2/api/public/create-invoice`, `GET …/download-invoice/{id}/pdf`.
- Klucz z „Dane i Ustawienia → Integracje”, nagłówek `ApiUserCompanyRoleKey`. Sekret: `ING_API_KEY`.
- Pola: nabywca (nazwa, adres, kraj, NIP + kraj NIP, e-mail), pozycje (nazwa, ilość, jednostka, netto, VAT, brutto, stawka), waluta (PLN, EUR, …), płatność (metoda, termin, konto).
- Stawki: `TAX_23`, `TAX_0`, `TAX_EXEMPT`, `TAX_NOT_LIABLE` (NP), `TAX_REVERSE_CHARGE`.
- Brak w API: edycja/korekta faktury, odczyt płatności, wersja EN. Faktury w PLN i EUR możliwe (pole `currency.rate`).
- Dokumentacja: https://www.ingksiegowosc.pl/uslugi-dodatkowe/integracje-e-commerce/api
- ING Pay (imoje) — bramka płatnicza ING; integracja z Księgowością wystawia faktury tylko w PLN. Nie zastępuje Stripe (weryfikacja karty bez obciążenia, karty zagraniczne). Zostajemy przy Stripe; ING Pay ewentualnie jako alternatywa dla BLIK/P24 w PLN.

## KSeF
- Obowiązkowy od 1.04.2026 dla wszystkich; **wyjątek do 31.12.2026**: podatnicy wystawiający faktury na < 10 000 zł brutto miesięcznie mogą wystawiać poza KSeF. Od 1.01.2027 obowiązek bez wyjątków.
- Faktury dla konsumentów (B2C) nie podlegają KSeF. Faktury dla firm zagranicznych: wystawiane w KSeF, ale nabywca dostaje PDF/wizualizację (brak dostępu do KSeF) — portal wysyła PDF e-mailem.
- ING Księgowość ma moduł KSeF — wysyłka z poziomu ING, nie z naszego API. Do sprawdzenia: czy faktura utworzona przez API trafia do KSeF automatycznie.

## VAT — kto, co, jaka stawka
Usługa: obliczenia w chmurze = usługa elektroniczna / usługa dla podatnika (art. 28b). **Klient potwierdził 28.10.2026: czynny podatnik VAT w Polsce, bez rejestracji VAT-UE.** Wniosek: do pierwszej sprzedaży firmie z UE trzeba złożyć VAT-R (aktualizacja, część C.3, pole 60). Do tego czasu portal nie wystawia faktur z odwrotnym obciążeniem dla firm z UE (blokada w formularzu danych do faktury z komunikatem).

| Klient | Miejsce opodatkowania | Stawka na fakturze | Dodatkowe obowiązki |
| --- | --- | --- | --- |
| Firma z Polski | Polska | 23% | KSeF (po limicie) |
| Osoba prywatna z Polski | Polska | 23% | faktura na żądanie, paragon niewymagany przy płatności elektronicznej na konto (do potwierdzenia) |
| Firma z UE z VAT-UE | kraj nabywcy | NP, „odwrotne obciążenie” (`TAX_REVERSE_CHARGE`) | rejestracja VAT-UE (VAT-R, pole 60) **przed pierwszą sprzedażą**; sprawdzenie NIP w VIES; informacja podsumowująca VAT-UE do 25. dnia miesiąca |
| Firma spoza UE | kraj nabywcy | NP (`TAX_NOT_LIABLE`), adnotacja „odwrotne obciążenie” | brak VAT-UE; dowód, że nabywca jest przedsiębiorcą (numer podatkowy, strona www) |
| Osoba prywatna z UE | do 10 000 € rocznie (42 000 zł): Polska, 23%; powyżej: kraj konsumenta | 23% PL albo stawka kraju konsumenta | powyżej progu: rejestracja do **OSS** (VIU-DO) — jedna deklaracja kwartalna zamiast rejestracji w każdym kraju |
| Osoba prywatna spoza UE | kraj konsumenta | NP w Polsce | formalnie VAT kraju konsumenta — w praktyce przy sporadycznej sprzedaży nieegzekwowalne; **decyzja: ograniczyć konta prywatne spoza UE lub wymagać danych firmy** |

Jeśli FP Solutions korzysta ze zwolnienia podmiotowego (< 200 000 zł rocznie): faktury krajowe „zw”, sprzedaż do firm z UE i tak wymaga rejestracji VAT-UE i informacji podsumowującej; limit liczy się od całej sprzedaży.

## Co portal robi automatycznie
1. Formularz danych do faktury: rodzaj (firma/osoba), kraj, NIP/VAT — walidacja VIES dla UE, GUS/biała lista dla PL.
2. Dobór stawki według tabeli wyżej; cena netto = koszt × mnożnik; przy 23% brutto = netto × 1,23.
3. Po zakończeniu obliczeń: faktura przez API ING w PLN (klient PL) lub EUR (zagranica), PDF do klienta e-mailem, link w portalu.
4. Rejestr sprzedaży do VAT-UE: panel admina pokazuje miesięczne zestawienie faktur z odwrotnym obciążeniem.

## Pytania do księgowej (przed uruchomieniem płatności)
- Czynny VAT czy zwolnienie? Czy jest rejestracja VAT-UE?
- Czy sprzedaż osobom prywatnym wymaga kasy fiskalnej (zwolnienie przy płatności na konto — poz. 37 załącznika do rozporządzenia)?
- Kurs do faktur w EUR: NBP z dnia poprzedzającego wystawienie — kto wpisuje (`currency.rate`)?
- Czy faktury z API ING trafiają do KSeF automatycznie?

Źródła: [API ING Księgowość](https://www.ingksiegowosc.pl/uslugi-dodatkowe/integracje-e-commerce/api), [ING Pay](https://www.ingksiegowosc.pl/uslugi-dodatkowe/ing-pay), [KSeF — limit 10 tys. zł (Infor)](https://ksiegowosc.infor.pl/ksef/7538967,limit-10-tys-zl-w-ksef-mozesz-byc-poza-systemem-nawet-az-do-2027-roku.html), [Sprzedaż usług do UE i poza UE (podatki.biz)](https://www.podatki.biz/artykuly/vat-sprzedaz-uslugi-do-kraju-ue-i-poza-ue-przez-podatnika-krajowego_65_52618.htm), [Usługi elektroniczne dla osób prywatnych (Poradnik Przedsiębiorcy)](https://poradnikprzedsiebiorcy.pl/-miejsce-opodatkowania-swiadczonych-uslug-elektronicznych-na-rzecz-osob-prywatnych-z-ue-i-spoza-ue), [Podatnik zwolniony a usługi do UE](https://poradnikprzedsiebiorcy.pl/-wewnatrzwspolnotowe-swiadczenie-uslug-przez-podatnika-zwolnionego-z-vat).
