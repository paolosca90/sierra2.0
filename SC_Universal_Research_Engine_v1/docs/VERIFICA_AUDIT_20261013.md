# Verifica dei rilievi e correzioni — 13 ottobre 2026

Audit di riferimento: `AUDIT_SIERRA_2_0_2026-10-13.md`, fornito dall'utente.
Base verificata: commit `388803a4a44f75df3fca16d458b6856cd14c767e`, con modifiche locali applicate durante questa verifica.

L'audit individua due bug riproducibili, F-03 e F-07, ora corretti. Gli altri rilievi descrivono soprattutto limiti del modello, controlli mancanti o estensioni funzionali. Sono state aggiunte mitigazioni e diagnostiche; non vengono dichiarati chiusi i requisiti che richiedono dati nativi, un nuovo periodo forward o un motore prop dedicato.

## Riscontro per rilievo

| ID | Verifica | Intervento ed esito |
|---|---|---|
| F-01 | Confermato: `managed_simulate` e `trace` operano su LAST, con costi espliciti e quantità fissa, senza bid/ask eseguibili, queue o partial fill. Il confronto scalare è interno. | Aggiunto `evidence_status.native_execution_parity=not_verified` nei nuovi report. **Aperto**: servono replay, fill nativi e confronto STOP/TARGET/TIMEOUT/GAP/EOD; nessuna riconciliazione Sierra eseguita in questa verifica. |
| F-02 | Confermato dai documenti di ricerca: periodi finali già consultati. Uno split temporale non prova indipendenza. | Nuovi risultati e interfaccia classificati come esplorativi; `holdout_independence` vale `known_reused` quando dichiarato nella configurazione, altrimenti `not_verified`. **Mitigato nella presentazione, aperto sul piano statistico**: nessun dato nuovo creato, nessuna correzione per confronti multipli o prova forward completata. |
| F-03 | Confermato: il numero di combinazioni veniva calcolato prima di congelare sensitivity. Precisazione: la firma del checkpoint era già costruita dopo la calibrazione. | **Corretto**: conteggio e budget dopo la calibrazione, validazione API sulla cardinalità effettiva; test di summary, journal e resume. La firma comprende anche i nuovi moduli di validazione ed economia strumenti. |
| F-04 | Confermato con fixture: un target raggiunto prima di un gap è escluso dal controllo esteso alla scadenza. È un criterio conservativo già documentato; non prova una distorsione necessariamente favorevole. | Aggiunto `execution_quality` con esclusioni per causa. Il criterio resta `full_horizon`. **Parziale**: i conteggi sono di barre, prima di segnali/sessioni/date ammesse; non sono conteggi di trade e non misurano la differenza di P&L rispetto al first-hit. Il confronto tra politiche resta da fare. |
| F-05 | Confermato: `evaluate` misura il drawdown della sequenza dei trade chiusi. | Aggiunti `drawdown_basis=closed_trade_equity` e `prop_rules=not_implemented`. **Aperto**: non è stato implementato un ledger mark-to-market né scelto un ruleset prop. Il campo storico `maxdd` conserva significato e compatibilità. |
| F-06 | Confermato: il port dichiara sessione NY 18:00, VA 70% e necessità di export punto-per-punto. Il collector scrive 26 livelli, ma la sua presenza non certifica equivalenza. | **Aperto**: nessuna estensione della parità TO default a Deluxe o ad altri parametri; rimangono gli avvisi specifici. Servono export nativi con DST, rollover e configurazioni effettivamente usate. |
| F-07 | Confermato: 7 secondi era accettato dall'API e respinto dal reader. | **Corretto**: regola condivisa in `bar_schema.py`, riusata da API, reader e rebar. Test HTTP 400 prima di pianificare o avviare il worker. Barre trade indipendenti dalla divisibilità della durata temporale. Rifiutati anche booleani negli input interi dell'API. |
| F-08 | Confermato come confine di fiducia locale; il token HTTP non isola Python dal sistema operativo. L'avviso esisteva nel README, ma mancava una conferma nell'importazione. | **Mitigato**: conferma esplicita per Python, SHA-256 integrale dei byte approvati, verifica prima di ogni accesso al modulo anche se in cache, esecuzione dei byte verificati senza riuso di `.pyc` obsoleti. Plugin preesistenti senza autorizzazione/hash devono essere reimportati. Nessuna sandbox o firma di un editore: codice fidato e dipendenze mantengono i permessi dell'utente. |
| F-09 | Confermata l'assenza di workflow versionati nella base. Il numero di run remoti citato dall'audit non è stato ricontrollato. | Aggiunto workflow push/PR: Ubuntu e Windows, Python 3.11/3.12, controllo sintassi e suite completa con smoke API e percorsi casuali. **Implementato localmente**; run remoti e required checks non ancora verificati/configurati. Build ACSIL resta separata. |
| F-10 | Confermato il perimetro NQ/ES. I valori esistenti sono coerenti con quel perimetro: non è un errore aritmetico sui contratti supportati. Era però presente un fallback implicito a ES per strumenti diversi nel worker/audit scalare. | Registro versionato NQ/ES per dashboard e audit scalare, metadati economici nel report e rifiuto esplicito dei simboli non supportati. Test P&L con quantità/commissioni e rifiuto MNQ/MES. **Mitigato**: supporto micro, regole dati e rollover generalizzati restano da implementare; nessun alias automatico. |

## Evidenza quantitativa e nativa

Le cifre principali citate nell'audit sono coerenti con i documenti locali: ricerca NQ EOD, campagne PRIMARY/INSTRUMENT, V3 per sessione e stress sullo storico precedente. Per NQ AM, lo stress indicato si riconcilia aritmeticamente: `335 - 98 * 2 * 5 = -645 USD`. Ciò verifica la trascrizione e il calcolo, non riproduce la ricerca sui tick originali.

Il piano V4 contiene sette aggregazioni per due strumenti. La struttura degli assi dichiarati è coerente con 5.184 combinazioni per blocco, 72.576 totali e 290.304 valutazioni su quattro fasi. Non è stato rilanciato il generatore né dedotto da questo conteggio che la campagna sia completata.

Confermati anche i blocchi statici del trader ACSIL: `SendOrdersToTradeService=0`, ARM disattivato per default, replay in corso e simulazione globale richiesti. La DLL non è stata compilata o provata in Sierra durante questa verifica.

## Verifica delle patch

- Baseline locale: **66 test superati**.
- Dopo le patch: **77 test superati**, inclusi 11 nuovi test di regressione in `tests/test_audit_regressions.py`.
- La regressione F-03 esegue l'orchestrazione completa su engine sintetico: sensitivity `[1,2,4,6,8]`, scelta congelata `[4]`, due combinazioni effettive, otto righe nel journal e seconda esecuzione senza nuove valutazioni train o duplicati. Non è un test di edge finanziario.
- La regressione F-07 attraversa l'endpoint reale con `TestClient` e verifica che planner e creazione del processo non siano chiamati.
- I test plugin coprono mancata autorizzazione, import senza esecuzione, modifica dopo caricamento, metadati legacy e API.
- Un test attraversa il vero `worker.Engine`, il kernel e l'audit scalare su tape sintetico: NQ/ES, due contratti, commissioni, prezzo target e P&L riconciliati.
- Verificati `compileall`, sintassi JavaScript con `node --check` e `git diff --check`.
- Avviso non bloccante già presente nella baseline: deprecazione di `httpx` nel TestClient Starlette. Nessun test fallito.

Comando della suite, dalla radice del repository:

```powershell
rtk proxy SC_Universal_Research_Engine_v1\.venv\Scripts\python.exe -m unittest discover -s SC_Universal_Research_Engine_v1/tests -q
```

## Compatibilità e lavoro restante

Le ricerche già completate non vengono riscritte. I checkpoint creati con il codice precedente continuano a essere rifiutati dalla protezione di identità quando cambia il modello: per eseguire le patch occorre una nuova ricerca. Il resume è verificato fra esecuzioni dello stesso codice aggiornato.

La modifica locale preesistente in `tools/summarize_multibar_campaign.py` è stata preservata. Nessun commit, push, ordine o cambiamento alle campagne storiche effettuato.

Per chiudere l'audit operativo restano: export e replay Sierra comparabili; protocollo e dati forward realmente non consultati; confronto fra screening conservativo e first-hit con copertura/P&L; motore prop con ruleset specifico; validazione autonoma MNQ/MES; esecuzione della matrice CI remota. Le patch non certificano un edge né idoneità al trading live.
