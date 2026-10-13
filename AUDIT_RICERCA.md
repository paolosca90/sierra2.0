# Audit e decisioni — Sierra Research Lab

## Rettifica dati del 13 ottobre 2026

I risultati in `output/ES_LIQUIDITY_EOD_FINAL` sono INVALIDI: l'alias ESM6.CME aveva prezzi memorizzati 100 volte maggiori e non era stato normalizzato. Non usare quei profitti/perdite o configurazioni per conclusioni operative. I precedenti NQ comprendono 383 giornate disponibili, con sei giornate assenti nel luglio 2026, e non costituiscono una copertura completa del periodo richiesto.

Su istruzione esplicita dell'utente, la nuova campagna PRIMARY_GRID_20261013 usa solo -CME, senza normalizzazione o riempimento dagli alias. ESM26-CME, se respinto per timestamp fuori ordine, e le giornate NQ mancanti sono esclusi e documentati. I risultati sono esplorativi: i periodi finali erano gia stati consultati nelle precedenti ricerche.

## Perché non usare il replay per l'intera ottimizzazione

L'ottimizzatore nativo presente rilancia il replay per cambiare gli input. Rimane utile per riconciliare poche configurazioni finaliste con Sierra, ma non elimina il costo di una passata completa per ogni combinazione. Il vecchio backtester offline separa il segnale dalla simulazione: riutilizzare frecce registrate va bene per SL/TP, non per modificare parametri che cambiano il segnale TO.

La nuova soluzione legge SCID una volta, costruisce footprint/VAP e indici, poi esegue kernel compilati Numba. Ricalcola realmente TO quando cambiano i suoi parametri. Il motore di gestione è comune a tutti i plugin. Le prove TPE sono eseguite in un processo locale separato dalla dashboard; non richiedono un replay Sierra per ogni trial.

## Problemi riscontrati

1. I record unbundled Sierra usano marcatori speciali nel campo Open: trattarli come OHLC aggregati esclude scambi validi. Il reader riconosce i marcatori definiti da `IntradayRecord.h` e richiede comunque NumTrades=1.
2. Un segnale su barra chiusa non può entrare retroattivamente sull'ultimo scambio della barra. Il motore osserva la chiusura alla stampa della barra seguente e applica un ritardo prima dell'ingresso.
3. Lo stop attraversato con un gap non può essere riempito sempre al prezzo ideale. I test coprono gap, simmetria long/short, ordine dei tick e slippage.
4. `TO_Deluxe_Levels.cpp` riempiva retroattivamente intervalli del passato e poteva propagare i livelli più recenti sulle barre precedenti. Aggiunta modalità ricerca causale, senza backfill. La DLL compilata resta nel workspace; l'installazione Sierra aperta non è stata sostituita.
5. L'ottimizzatore nativo richiedeva correzioni per applicare input fissi e indici sparsi. È conservato come percorso di verifica nativa.
6. Il rollover fisso al giovedì anticipava la liquidità osservata nei `.dly` NQ/ES. Sostituito nella dashboard con tabella per scadenza, operativa dalla sessione successiva al sorpasso volume completato.
7. `ESM26-CME.scid` contiene timestamp fuori ordine: rifiutato. Gli alias .CME sono ora esclusi: la campagna usa solo i -CME validi e riporta i periodi omessi. Nessun ordinamento artificiale dei tick.

## Confronto delle alternative

| Componente/repository | Utilità | Decisione |
|---|---|---|
| [TraderOracle/SierraChart](https://github.com/TraderOracle/SierraChart/blob/main/TOReversalEngine-README.md) | Logica TO basata su footprint/VAP | Port dedicato e verifica contro export nativo |
| [SierraPy](https://github.com/NickS785/SierraPy) | Accesso/parsing SCID | Riferimento; da solo non simula ACSIL e gestione ordini |
| [OPTD starter](https://github.com/drewautomates/optd-starter) | Lettura dati e base di ricerca | Materiale di confronto, non sostituto completo |
| [SierraChartStrategyOptimizer](https://github.com/tanchekwei/SierraChartStrategyOptimizer) | Ricerca nativa via replay | Solo verifica di finalisti, non motore per grandi griglie |
| [vectorbt](https://github.com/polakowo/vectorbt) | Calcolo vettoriale di molte strategie | Non risolve la replica ACSIL e il dettaglio dei fill footprint |
| [backtesting.py](https://github.com/kernc/backtesting.py) | Strategie bar-based | Non adatto da solo all'ordine intrabar richiesto |
| [Optuna](https://optuna.org/) + NumPy/Numba | Ricerca a budget e kernel compilati | Usati nel motore locale |

## Cosa è verificato

- Port TO predefinito: 9.299 barre NQ, zero discordanza di frecce; massimo errore score circa 5,97e-8; zero discordanza OHLC e metriche controllate. Report `output/PARITY_NQ.json`.
- Test automatici per reader, causalità, first-hit, gap, costi, trailing/BE, combinazioni, rollover, chiusura EOD e API.
- Dashboard: esecuzione reale TO + livelli + trailing/BE, risultati persistenti e audit scaricabile. Primo collaudo: 32 trial in 6,2 s su 7 trade date. Sei trade holdout ricontrollati scalarmente, tutti coincidenti.
- Benchmark iniziale NQ: 800 trial distribuiti su due famiglie e quattro fasi, 383 trade date / circa 189,8 milioni di tick, 185,76 s incluse preparazione e compilazione. Il vecchio rollover non è quello finale: il dato dimostra velocità, non validità della strategia attuale.

## Cosa non è ancora certificato

La parità TO riguarda i default e il dataset verificato. Il port Deluxe deve essere confrontato con export puntuale Sierra; sono fornite DLL/collector per questo. Il controllo scalare automatico verifica ogni trade pubblicato dalla dashboard contro il modello di esecuzione interno, non contro fill live o Trade Activity Log Sierra.

La modalità corrente usa contratti separati, prezzi reali e warmup per contratto. Non ricostruisce esattamente il continuo back-adjusted e i suoi livelli intercontratto. Il drawdown è sui trade chiusi; non è il drawdown intratrade usato da alcune prop firm. Sono escluse finestre con dati/tempi di esecuzione insufficienti. L'assenza di volume/spread/queue completi impedisce di affermare che un fill simulato sarà ottenibile live.

I risultati iniziali non dimostrano un edge robusto: sul vecchio esperimento NQ entrambe le famiglie avevano walk-forward di sviluppo negativo; il piccolo profitto finale con livelli non basta. I nuovi run con rollover/EOD corretti sono riesecuzioni metodologiche sullo stesso storico, non un nuovo holdout indipendente.

## Documentazione primaria

- [Formato SCID Sierra](https://www.sierrachart.com/index.php?page=doc/IntradayDataFileFormat.html): layout e record intraday, insieme all'header locale `IntradayRecord.h`.
- [Backtesting Sierra](https://www.sierrachart.com/index.php?page=doc/Backtesting.php): modalità native e limiti delle simulazioni.
- [Continuous Futures Contract](https://www.sierrachart.com/index.php?page=doc/ContinuousFuturesContractCharts.html): selezione da volumi daily, sessioni e aggiustamenti dai settlement. La tabella causale implementata ritarda deliberatamente la decisione alla sessione successiva.
- [Formato daily CSV](https://www.sierrachart.com/index.php?l=doc%2FTextCSVDataFormat.html): i `.dly` locali contengono date, prezzi, volumi e open interest.

Per l'uso quotidiano vedere `README_DASHBOARD.md`.

## Riesecuzione con liquidita e chiusura giornaliera

NQ, aprile 2025–settembre 2026: 800 trial in 189,81 s, inclusi 74,37 s di preparazione/JIT. Tabella da volumi daily e cutoff 16:55 NY.

| Variante | Trade WF | Netto WF | Trade finali | Netto finale | Stress +2 tick |
|---|---:|---:|---:|---:|---:|
| TO | 1257 | -14.130 USD | 519 | -2.930 USD | -8.120 USD |
| TO + livelli | 277 | -12.205 USD | 66 | +1.570 USD | +910 USD |

La famiglia con livelli era scelta sullo sviluppo prima del holdout, ma entrambi i walk-forward sono negativi. Il holdout e gia stato visto nei run precedenti: non e nuova evidenza indipendente. Fonte: `SC_Universal_Research_Engine_v1/output/NQ_LIQUIDITY_EOD/SUMMARY.json`.

Collaudo web con EMA + RSI in OR, filtro livelli, SL/TP disattivati: 3 trade di report tutti chiusi END_OF_DAY entro le 16:55 NY; 1.217.578 tick controllati dal simulatore scalare, nessun mismatch. Questo e un test funzionale, non una strategia validata.

## Griglia completa con pesi, 13 ottobre 2026

Completata PRIMARY_GRID_20261013: 29.160 configurazioni uniche e 116.640 valutazioni su quattro finestre. Solo SCID -CME senza normalizzazione: 383 trade date NQ e 324 ES; sei giornate NQ e il periodo ESM26 del 17 marzo - 15 giugno 2026 esclusi. Confronto completo in `SC_Universal_Research_Engine_v1/output/PRIMARY_GRID_20261013/RISULTATI.md`.

Tutti i walk-forward sono negativi; nessun edge robusto dimostrato nella griglia. Piccoli finali positivi per le famiglie con livelli (11 trade NQ, 29 ES), con intervalli descrittivi che includono zero. Le date finali erano gia note. 757 trade controllati su 2.794.974 tick; chiusura entro 16:55 NY e assenza di sovrapposizioni verificate. 50 test passati.

Ottimizzazioni: maschere temporali riutilizzate, enumerazione esaustiva senza shuffle, metriche footprint riutilizzate tra pesi. Reweighting identico bit per bit su 20.000 barre reali e 15 profili; benchmark specifico score 0,124 s contro 0,014 s. Questo rapporto non e lo speedup dell'intero backtest. Retry su lock transitori Windows del file progress; attesa del rilascio del processo prima di avviare la ricerca successiva. Default riserva RAM 4 GiB, eccezione 3 GiB per questa campagna con Sierra chiuso.

## V2: scale per strumento e campione ampio

Completata INSTRUMENT_GRID_20261013: griglie NQ ed ES profilate sul primo train, 19 rapporti di peso incluse quattro ablazioni. Train minimo 200 trade, 30 giorni attivi e 40 trade per sotto-periodo. Conteggi finali NQ 105→204, NQ+livelli 11→211, ES 57→265, ES+livelli 29→88. Il finale usa l'ultimo 20% dei giorni disponibili. Una finestra WF ES+livelli resta insufficiente (33 trade).

Tutti i WF sono negativi. NQ+livelli finale +1.015 USD, WF -9.000 USD, stress +2 tick -1.095 USD: risultato fragile. Periodi gia noti; parita dei livelli Sierra non ancora certificata. Report CONFRONTO_CAMPIONE.md e diagnostica riproducibile in output/INSTRUMENT_GRID_20261013.

87.552 valutazioni, 2.750 trade e 4.423.409 tick verificati; 57 test superati. Introdotti journal dei trial e ripresa con verifica di codice/dati/parametri. Riserva 2 GiB per questa campagna offline con Sierra chiuso; default generale 4 GiB.
