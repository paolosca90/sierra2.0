# TO: controllo su storico aggiuntivo

Nessuna ottimizzazione: quattro regole V3 congelate per strumento, valutate nei periodi precedenti disponibili. Le regole derivano da dati successivi: è uno stress test storico retrospettivo, non una validazione temporale indipendente.

| Strumento | Periodo richiesto | Ingressi NY | Giorni disponibili | Trade | Netto USD | Stress +2 tick USD |
|---|---|---|---:|---:|---:|---:|
| NQ | 2025-01-02 / 2025-03-31 | ALL | 63 | 106 | -4545.00 | -5605.00 |
| NQ | 2025-01-02 / 2025-03-31 | RTH | 63 | 40 | -2415.00 | -2815.00 |
| NQ | 2025-01-02 / 2025-03-31 | AM | 63 | 56 | -4165.00 | -4725.00 |
| NQ | 2025-01-02 / 2025-03-31 | PM | 63 | 29 | -700.00 | -990.00 |
| ES | 2025-01-02 / 2025-03-31 | ALL | 63 | 87 | -3422.50 | -5597.50 |
| ES | 2025-01-02 / 2025-03-31 | RTH | 63 | 36 | -955.00 | -1855.00 |
| ES | 2025-01-02 / 2025-03-31 | AM | 63 | 32 | -2660.00 | -3460.00 |
| ES | 2025-01-02 / 2025-03-31 | PM | 63 | 24 | -945.00 | -1545.00 |
| ES | 2022-06-21 / 2023-03-06 | ALL | 179 | 274 | -9907.50 | -16757.50 |
| ES | 2022-06-21 / 2023-03-06 | RTH | 179 | 123 | -3140.00 | -6215.00 |
| ES | 2022-06-21 / 2023-03-06 | AM | 179 | 97 | -5035.00 | -7460.00 |
| ES | 2022-06-21 / 2023-03-06 | PM | 179 | 101 | -3805.00 | -6330.00 |

ALL = tutte le ore ammesse; RTH 09:30–16:00; AM 09:30–12:00; PM 12:00–16:00. Costi, stop, TP, BE e trailing identici alle regole V3 selezionate sul train. Una posizione alla volta, uscita entro 16:55 New York. Nessun filtro Deluxe.

## Misura del segnale senza stop

Ogni segnale ammissibile viene confrontato con una barra dello stesso contratto, trade date, ora NY e fascia di range medio delle ultime 20 barre chiuse. Il controllo mantiene la direzione del segnale. Seed 20261013, un controllo per evento. Misurati rendimenti a 1/3/5/10/30 minuti ed escursioni favorevole/contraria sui tick. Gli eventi possono sovrapporsi e non sono trade eseguiti. Il bootstrap per blocchi di 5 giornate è descrittivo, senza correzione per confronti multipli.

| Strumento | Periodo | AM, minuti | Eventi abbinati | Movimento medio tick | Vantaggio sul controllo tick | CI95 vantaggio tick |
|---|---|---:|---:|---:|---:|---|
| NQ | 2025-01-02 | 1 | 63 | -3.94 | -5.49 | -20.54 / 10.45 |
| NQ | 2025-01-02 | 3 | 63 | -8.71 | 1.29 | -24.39 / 28.13 |
| NQ | 2025-01-02 | 5 | 62 | -7.37 | 15.89 | -17.48 / 51.36 |
| NQ | 2025-01-02 | 10 | 63 | -34.32 | -9.14 | -49.79 / 22.69 |
| NQ | 2025-01-02 | 30 | 63 | -37.32 | 20.84 | -29.73 / 76.25 |
| ES | 2025-01-02 | 1 | 33 | -0.55 | -1.00 | -4.16 / 2.18 |
| ES | 2025-01-02 | 3 | 35 | -1.80 | 0.31 | -4.00 / 4.03 |
| ES | 2025-01-02 | 5 | 35 | -1.03 | -1.40 | -6.24 / 3.80 |
| ES | 2025-01-02 | 10 | 34 | -5.29 | -2.21 | -10.80 / 5.31 |
| ES | 2025-01-02 | 30 | 33 | -12.85 | 0.97 | -10.59 / 15.29 |
| ES | 2022-06-21 | 1 | 99 | -0.01 | 1.09 | -0.44 / 2.82 |
| ES | 2022-06-21 | 3 | 101 | -1.75 | -0.75 | -3.51 / 2.04 |
| ES | 2022-06-21 | 5 | 101 | 0.34 | 2.44 | -2.89 / 8.16 |
| ES | 2022-06-21 | 10 | 98 | -0.95 | 3.54 | -1.78 / 8.71 |
| ES | 2022-06-21 | 30 | 99 | -0.87 | 6.14 | -0.30 / 12.69 |

## Interpretazione e limiti

Le 12 combinazioni congelate perdono nel controllo storico. NQ AM perde 4165 USD su 56 trade a gennaio–marzo 2025: il finale recente positivo non si mantiene in questo regime. Gli intervalli del vantaggio AM sul controllo includono zero a tutte le cinque durate e nei tre periodi. Non dimostrano assenza universale di informazione, ma non confermano un vantaggio direzionale robusto nelle regole testate.
Tre celle RTH hanno un intervallo del vantaggio relativo positivo: NQ a 5 e 30 minuti nel 2025, ES a 3 minuti nel 2025. I campioni sono 37–42 eventi; il rendimento medio del segnale rimane negativo su NQ e inferiore ai costi simulati su ES. Sono confronti esplorativi, non prove di significatività dopo selezione.
I file 2023–2024 vuoti non sono storico utilizzabile. Non si uniscono periodi discontinui per fingere copertura continua. Escluse da ESH23 le trade date 2023-02-27, 2023-02-28 e 2023-03-06. Restano i limiti di esecuzione su ultimo prezzo e la parità Sierra non completa.
Verifica: 1005 esecuzioni auditabili, 5207962 tick; tutte le uscite entro 16:55; 61 test superati.