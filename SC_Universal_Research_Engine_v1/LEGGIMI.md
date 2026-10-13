> **Aggiornamento ottobre 2026:** per il motore veloce e la dashboard usare `../README_DASHBOARD.md` e `../AVVIA_DASHBOARD.cmd`. Il percorso replay descritto sotto è quello legacy; le DLL di ricerca sono ora compilate nel workspace.

# SC Universal Research Engine v1.0 — guida operativa

**Stato:** codice consegnato, suite Python superata. La DLL ACSIL e la build MSVC devono ancora essere compilate e provate sul PC Windows/Sierra dell'utente. Questa NON è una strategia con edge accertato.

## Obiettivo / componenti

- **Sorgente segnali ACSIL**: qualunque indicatore con subgraph LONG e SHORT. TOReversalEngine è solo il primo caso.
- **UniversalSignalTrader.cpp**: invia ordini ESCLUSIVAMENTE nel simulatore di replay Sierra, su BARRE CHIUSE, in modalità global simulation ON, `SendOrdersToTradeService=0` forzato. Consente SL=0, TP=0 e uscita alla prossima freccia opposta o max barre. Di default `ARM=No`.
- **SierraChartStrategyOptimizer (MIT)**: sorgente pinned e patchato. Cambia input di **UNO studio alla volta**, rilancia replay, esporta statistiche del simulatore. Richiede Visual Studio C++ per build multifile.
- **universal_tick_optimizer.py**: legge `.scid` e CSV del Collector in sola lettura, esegue first-hit di SL/TP, ricerca parametri Optuna sul train cronologico, valuta un holdout cronologico senza ottimizzarlo; dai 30 giorni disponibili esegue anche walk-forward rolling. Lavora su LAST TRADE, non libro ordini e non riproduce fill veri.
- **SierraPy/OPTD**: sorgenti upstream importati come materiali di ricerca/audit. Il motore offline v1 usa un proprio lettore NumPy SCID verificato con test sintetici; non dichiara di chiamare direttamente SierraPy o OPTD.

## 1 — Estrai e installa una sola volta

Scaricare lo ZIP `SC_Universal_Research_Engine_v1.zip` e incollarlo in `Downloads`. In PowerShell:

```powershell
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\SC_Universal_Research_Engine_v1.zip" -DestinationPath "$env:USERPROFILE\Downloads" -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\SC_Universal_Research_Engine_v1\tools\INSTALLA_E_PREPARA.ps1"
```

L'installatore esegue: copia sorgenti su `Documents\SC-OrderFlow-Lab\universal-research-v1`, importa tre repository a SHA fissi nelle cartelle di ricerca, crea una COPIA del motore originale sotto `C:\SierraChart\ACS_Source\StrategyOptimizer_Universal`, applica patch a quella COPIA, prepara `.venv` e lancia i test. Il file `UniversalSignalTrader.cpp` viene copiato in `ACS_Source` con backup se preesistente. **Non tocca `TOReversalEngine.cpp`, non compila DLL e non effettua ordini.** Internet necessario per GitHub/PyPI; Python 3.x e launcher `py` necessari.

Se l'installatore risponde che una cartella precedente esiste, non la sovrascrive. Se si vuole rifare l'importazione, spostare PRIMA le cartelle interessate in un archivio/backup (non eliminarle alla cieca).

## 2 — Ricerca offline sui tuoi dati NQ (PRIMA di compilare l'ottimizzatore)

Controlla che esistano:

```text
C:\SierraChart\Data\TO_REPLAY_NQ_TEST01.csv
C:\SierraChart\Data\NQZ26-CME.scid
```

Poi:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Documents\SC-OrderFlow-Lab\universal-research-v1\tools\AVVIA_PRIMA_ANALISI.ps1"
```

Il lettore **blocca la ricerca first-hit** quando meno del 95% dei record SCID segue la convenzione di singolo trade. Questo NON significa che il file sia per forza sbagliato: significa che non possiamo stabilire con sufficiente confidenza quale soglia sia stata toccata per prima. Si può fare una prova diagnostica a prezzi aggregati con:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Documents\SC-OrderFlow-Lab\universal-research-v1\tools\AVVIA_PRIMA_ANALISI.ps1" -ExploratoryAggregated -Trials 30
```

**La prova esplorativa NON dimostra fill accurati.** Prima di ottimizzare davvero, preferire rigenerare/controllare dati tick e verificare il replay nativo. Non alzare arbitrariamente la tolleranza: se il file registrato ha OHLC aggregati, l'ordine interno del movimento può essere sconosciuto.

Nella cartella `output\NQZ26-CME_...`: `REPORT.md`, `SUMMARY.json`, `TRAIN_OPTUNA_TRIALS.csv`, `HOLDOUT_TRADES.csv`, `ALL_TRADES_EXPLORATORY.csv`, e oltre 30 giorni anche `WALK_FORWARD_FOLDS.csv`/`WALK_FORWARD_TRADES.csv`.

**Attenzione alla validità:** dall'1 al 9 ottobre sono circa otto giornate. Non abbiamo dati sufficienti per dichiarare stabilità OOS. Optuna su un campione così breve è solo un test di funzionamento, non una selezione strategica.

## 3 — Compila l'adattatore simulato in Sierra

`Analysis → Build Custom Studies DLL → Select Files → UniversalSignalTrader.cpp → Build → Remote Build`. Aggiungi `Universal Signal Trader (REPLAY SIM ONLY)` **sotto** TOReversalEngine a un grafico duplicato, NON al chartbook prop/live. Parametri predefiniti (in sorgente index zero-based):

| In (visuale 1-based) | Indice ACSIL | Valore per TOReversalEngine |
|---|---:|---|
| Signal Source Study ID | 0 | TOReversalEngine ID 1 |
| LONG Subgraph | 1 | 10 |
| SHORT Subgraph | 2 | 11 |
| Signed Score Subgraph | 3 | 9 |
| ARM | 4 | No all'inizio; poi Yes solo per replay SIM |
| Contracts | 5 | 1 |
| SL ticks | 6 | 0 disattiva |
| TP ticks | 7 | 0 disattiva |
| Min Score | 8 | 0.30 |
| Long/Short enabled | 9/10 | Yes |
| Close on opposite | 11 | Yes |
| Max Hold Bars | 12 | 60 (0 disabilita) |

Il simulatore può quindi aprire su freccia confermata e chiudere alla prossima freccia opposta **oppure** a 60 barre, anche senza SL e TP. Se vuoi SOLO la prossima freccia, imposta `Max Hold Bars = 0` ma usa esclusivamente replay `Sim#`: si tratta di test virtuale senza limite teorico di perdita. Nell'ottimizzazione SL/TP imposta SL/TP >0.

**Non armeggiare con Trade Simulation Mode sui chartbook reali.** Usa una copia, conto `Sim#` dedicato e verifica `Trade >> Trade Simulation Mode On`, mai live; questo studio impone `SendOrdersToTradeService=0` nel codice, ma non è stato ancora verificato sulla tua build.

## 4 — Compila l'Optimizer con Visual Studio Build Tools

Il repository originale è C++ **multifile** (`StrategyOptimizer.cpp` + 9 altri sorgenti). Non tentare `Remote Build` del solo `StrategyOptimizer.cpp`.

Se sul PC sono presenti **Visual Studio 2022 Build Tools (Desktop development with C++)** o Visual Studio con MSVC, esegui:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Documents\SC-OrderFlow-Lab\universal-research-v1\tools\COMPILA_OPTIMIZER_LOCALE.ps1"
```

Lo script usa `vswhere.exe`, rileva l'installazione MSVC, compila tutti i sorgenti insieme e salva la DLL in `C:\SierraChart\Data\StrategyOptimizer_Universal_YYYYMMDD_HHMMSS.dll`. Se la build non riesce, incolla **l'intero log**. Non scaricare DLL precompilate da fork casuali.

## 5 — Primo test di ottimizzazione sul replay Sierra

1. **Salva un Chartbook di TEST** con NQ, TOReversalEngine, UniversalSignalTrader e Strategy Optimizer (ordine studi: TO, trader, optimizer).
2. Usa `Trade Simulation Mode ON` e un account `Sim#` **dedicato, vuoto**. L'optimizer può cancellare i vecchi trade del conto per simbolo durante un nuovo run: NON usare un Sim# con statistiche importanti.
3. Configura sul trader `ARM=Yes` **soltanto durante replay**; lascia TO invariato.
4. Aggiungi l'ottimizzatore al chart, seleziona come `Target Study` **Universal Signal Trader**, non TOReversalEngine.
5. `Config File Path` = `C:\SierraChart\Data\StrategyOptimizerConfig_Universal.json`; copia lì `config\optimizer_simtrader_smoke.json` e verifica `startDate` adatto e `replayMode = 3` (Calculate at Every Tick).
6. Aggiungi alla barra gli ACS Buttons `CS6`, `CS7`, `CS8`, `CS9` come nel README upstream. Clicca **CS7 Verify**: conferma 4 combinazioni (SL {40,60}, TP {60,80}), senza errori; poi **CS8 Start**.
7. Al termine, verifica CSV dei trade e JSON per combinazione. Ripeti identica combinazione due volte per assicurare replicabilità e che non compaiano residui di altri backtest.

**Nota sull'ottimizzazione dei segnali originali:** l'Optimizer sa mutare UN target studio alla volta. Per cambiare soglie di TO, fai un campaign con TO come target e il trader che legge i suoi subgraph; per cambiare SL/TP scegli il trader come target. I due sweep successivi vanno condotti esclusivamente sui dati train. Prima di ottimizzare parametri `In:60..79`, risolvi separatamente il problema dell'elenco incompleto di TO nel GUI; questo pacchetto NON cambia TOReversalEngine.

## 6 — Validazione del vantaggio, non solo ricerca del massimo storico

- Fuori campione temporale, nessuna ricerca sul periodo di test.
- Riproducibilità 1× vs accelerato / replay identico più volte.
- MFE/MAE realizzabili **prima** dell'uscita, non soltanto sull'intero orizzonte; rapporto ordine SL/TP first-hit.
- Segnali realizzati dopo la loro disponibilità temporale, non al prezzo retroattivo della barra precedente.
- Costi completi: spread, slippage (specialmente stop), commissioni, margini delle prop e finestre di notizie.
- Controlli su baseline senza segnale e robustezza vicina dei parametri.
- Pochi giorni di test non certificano alcun edge.

## Sicurezza e limiti specifici

1. **No live**: `SendOrdersToTradeService=0` imposto ogni chiamata; REPLAY_RUNNING e GlobalTradeSimulationIsOn obbligatori.
2. **Sierra schema**: il programma offline usa `.scid` record da 40 byte, 56-byte header e timestamp SC UTC; rifiuta formati inattesi. Le conversioni orarie cercano l'offset in base alla corrispondenza dei CLOSE 1m; per periodi che attraversano il cambio ora, dividere per stagione o sviluppare mappatura DST.
3. **Quote missing**: solo LAST TRADE; stop/target trigger non garantiscono esecuzioni reali, né la posizione in coda degli ordini limite.
4. **Collisioni**: strategia offline consente un solo trade simultaneo. Nel replay nativo ordini working e policy Sierra possono creare differenze; devono essere riconciliate.
5. **Ottimizzazione due studi**: non implementata congiuntamente, due campagne separate. Non dichiararlo ottimizzatore pienamente universale finché non esiste un registro cross-study e report OOS comparabili.
6. **Dataset corto / riproducibilità**: validazione sul tuo NQ richiede il `.scid` reale. I test inclusi sono sintetici e servono a validare software, NON performance finanziaria.

### Sorgenti GitHub importati (versioni fissate)

| Repo | Commit | Uso |
|---|---|---|
| https://github.com/tanchekwei/SierraChartStrategyOptimizer | `3e1d466e97864f8bb107bca42b4733f0aed9a5dc` | optimizer replay/CSV C++ |
| https://github.com/NickS785/SierraPy | `751137e750007d3411ca5afe6b8e9c6106b6d053` | riferimento reader .scid |
| https://github.com/drewautomates/optd-starter | `8f8fdff37115fd97bcc008e13c9960968fa5b64f` | esempi anti-bias |

Problemi upstream corretti nella COPIA: signed loop index; non ignorare fixed input `increment=0`; includere input con indici sparsi; `skipEmptyPeriods` nei JSON generati. Gli originali restano invariati.
