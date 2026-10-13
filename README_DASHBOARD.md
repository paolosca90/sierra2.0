# Sierra Research Lab — avvio e uso

Dashboard locale per ricerca NQ/ES sui file reali Sierra. Doppio clic su **AVVIA_DASHBOARD.cmd** nella stessa cartella. Il launcher riapre il server già avviato oppure sceglie una porta libera. Indirizzo salvato in `SC_Universal_Research_Engine_v1/dashboard_url.txt`.

## Flusso operativo

1. Seleziona NQ o ES, periodo e cartella Data. Premi **Verifica dati**.
2. Scegli l'indicatore principale. Per ogni parametro lascia il valore fisso oppure seleziona **Ottimizza** e inserisci valori separati da virgole: `0.1, 0.2, 0.3`. Usa il punto come separatore decimale.
3. Aggiungi conferme e filtri. **Esempio TO + Livelli** prepara una ricerca con parametri TO, distanza dai livelli, SL, TP e soglia variabili.
4. Imposta SL/TP/trailing/break-even, quantità e costi. Prezzi di stop e target espressi in **tick**, commissione round-trip per contratto in dollari.
5. Scegli TPE e budget, oppure griglia completa. Il budget è **per fase**: tre fasi walk-forward più un refit possono produrre 4 × budget prove. TPE campiona lo spazio, non garantisce il massimo globale. La griglia è limitata a 10.000 combinazioni.
6. Avvia. I risultati sono persistenti nell'archivio e scaricabili in CSV/JSON.

## Combinare indicatori

- **AND:** il principale genera l'ingresso; tutte le conferme devono avere l'ultima direzione concorde entro la finestra di barre indicata. Zero richiede la stessa barra.
- **OR:** basta un segnale sulla barra corrente; segnali opposti sulla stessa barra annullano l'ingresso. La finestra delle conferme si applica solo ad AND.
- I filtri di prezzo sono sempre obbligatori, anche in modalità OR.
- Ogni indicatore ha parametri indipendenti. Massimo cinque conferme/filtri oltre al principale.
- TO Deluxe: attualmente sono implementati i livelli con impostazioni di sessione predefinite; è ottimizzabile la distanza dai livelli. Non tutti gli input dell'ACSIL Deluxe sono portati.

## Tick, ordini e chiusura giornaliera

La lettura usa i singoli scambi SCID nell'ordine del file. Sono ammessi i marcatori Sierra degli scambi unbundled; record aggregati, prezzi fuori griglia, volume bid/ask incoerente e timestamp decrescenti vengono rifiutati. Il file originale non viene modificato né riordinato. Per la campagna corrente si usano esclusivamente i file -CME, senza normalizzazione. Gli alias .CME sono bloccati per evitare scale prezzi incompatibili. In modalita available_data_only le giornate mancanti e i contratti non validi vengono esclusi e dichiarati nel report; la modalita normale resta rigorosa sulla copertura.

Il segnale è osservabile alla prima stampa della barra successiva. L'ingresso avviene su una stampa successiva al ritardo configurato. Il motore gestisce una posizione per strumento. Stop a mercato con gap/slippage; target al prezzo limite dopo il trade-through richiesto; nessun miglioramento di prezzo inventato. Trailing e break-even diventano efficaci dal tick successivo all'aggiornamento.

**Chiusura obbligatoria entro le 16:55 America/New_York**, anticipabile nella dashboard. L'ordine di chiusura viene modellato alle 16:54:59 e riempito alla prima stampa successiva, obbligatoriamente entro le 16:55. Non viene scelto retroattivamente l'ultimo tick precedente alla chiusura. Un percorso senza stampa utilizzabile entro il limite viene escluso; non si trascina la posizione overnight. Il CSV distingue `END_OF_DAY`, `TIMEOUT`, `STOP`, `TARGET`. Il fuso gestisce automaticamente il cambio dell'ora legale USA.

Le finestre con gap oltre i limiti impostati sono escluse prima del backtest: criterio conservativo sull'intero percorso fino alla scadenza, anche se un trade avrebbe potuto terminare prima. Le prime 500 barre sono warmup. Sono supportate barre temporali, non Range/Renko/Volume bars.

Ogni trade nei report walk-forward e holdout della dashboard viene verificato da un **secondo simulatore scalare**, che visita ogni tick senza salti. Una discordanza su indice di uscita, motivo o P&L blocca il report. In **Operazioni → Tick per tick** puoi scaricare anche tutte le stampe, stop prima/dopo, aggiornamenti trailing/BE, fill e risultato di una specifica operazione.

Questo verifica la coerenza interna. Non equivale alla riconciliazione completa con Sierra Trade Activity Log: il simulatore usa LAST e slippage, non ricostruisce spread bid/ask, coda degli ordini o fill live.

## Contratti e liquidità

La dashboard costruisce una **tabella fissa per scadenza** usando i volumi dei file daily `.dly` di Sierra. Il nuovo contratto diventa operativo dalla sessione successiva al primo giorno completato in cui supera il vecchio per volume. Si evita così di usare il volume finale della giornata per decidere all'inizio della stessa giornata. Nessuna data dipende dal profitto della strategia.

Le esecuzioni usano i `.scid`; i `.dly` servono solo per decidere il rollover. La tabella riporta le due scadenze, la data della decisione, i volumi, la prima trade date e gli hash delle fonti. I periodi iniziano alle 18:00 New York del giorno precedente la trade date.

Questa modalità usa **prezzi non aggiustati dei singoli contratti**, come concordato durante lo sviluppo. Non replica esattamente il continuo Sierra “Volume Based Rollover, Back Adjusted”: Sierra può collocare la transizione sul giorno del sorpasso e aggiusta il passato usando differenze di settlement. Gli indicatori hanno warmup sul singolo contratto; i livelli che attraversano rollover/settimane/mesi richiedono un confronto dedicato con il grafico continuo Sierra.

Se manca un file, la dashboard indica il contratto/intervallo richiesto. Per i daily mancanti apri il relativo Historical Daily in Sierra. Per gli SCID imposta archiviazione a **1 tick** e completa il download in Sierra; poi ripeti la verifica. Il programma non cambia automaticamente le impostazioni o i dati di Sierra.

## Indicatori disponibili e import

Pronti: TO Reversal, RSI Wilder con rientro dalle bande, incrocio EMA, MACD/signal, stocastico %K non smussato, filtro TO Deluxe causale.

Il motore è estensibile a indicatori/oscillatori tramite il protocollo Python in `dashboard/static/example_indicator.py`. Il plugin dichiara `METADATA` con nome e parametri e implementa `compute(data, params)`. Restituisce un array per barra: zero = nessun segnale, positivo = long, negativo = short, valori finiti tra -1 e 1. I prezzi forniti sono in punti; tempi UTC in microsecondi dall'epoca Sierra. Il plugin deve essere causale. Un controllo a prefissi individua alcuni casi di lookahead, senza costituire una prova completa.

Importa solo codice Python locale di cui ti fidi: viene eseguito sul PC nel processo della ricerca, non in una sandbox. Un `.cpp` ACSIL viene analizzato per rilevare gli input ma resta **adattatore richiesto**. Un ACSIL arbitrario non diventa eseguibile fuori da Sierra con il semplice caricamento del file. Per ogni nuovo port occorre verificare la parità contro un export Sierra.

## Validazione e lettura dei risultati

- Split cronologico: ultimo 20% delle trade date riservato al holdout, tre finestre expanding sullo sviluppo quando disponibili.
- Obiettivo di selezione: netto meno 0,75 × drawdown dei trade chiusi, con minimo trade configurabile.
- La configurazione viene scritta in `SELECTION_LOCK.json` prima del test finale. Gli hash dati e codice, versioni e seed sono salvati.
- La dashboard mostra equity, trade, drawdown, walk-forward e stress di due tick aggiuntivi per trade.
- Dopo aver visto il holdout, quelle date non sono più nuove evidenze indipendenti per ulteriori scelte. Un profitto isolato non dimostra edge.

TO ai parametri originali è stato confrontato su **9.299 barre NQ**, con zero mismatch su frecce, score oltre tolleranza, OHLC e quattro metriche. Questo non verifica ogni parametro possibile né il port Deluxe: la parità Deluxe e la riconciliazione dei fill Sierra restano aperte.

## File e manutenzione

- `SC_Universal_Research_Engine_v1/dashboard_jobs`: configurazioni, report, log e audit delle ricerche web.
- `SC_Universal_Research_Engine_v1/.scid_cache`: snapshot/cache immutabili delle finestre lette. Conservare le cache per poter riprodurre l'audit di un risultato salvato.
- `SC_Universal_Research_Engine_v1/output`: benchmark e ricerche CLI. I risultati `NQ_18MONTHS_SCID` usano la precedente regola di rollover: benchmark tecnico, non configurazione attuale.
- `SC_Universal_Research_Engine_v1/build_v2`: DLL di supporto compilate nel workspace, non installate nel Sierra aperto.
- `AUDIT_RICERCA.md`: analisi del codice, scelta del motore e limiti.

Se sposti il progetto, ricrea l'ambiente e rigenera le cache (i report contengono percorsi assoluti):

```powershell
py -3 -m venv SC_Universal_Research_Engine_v1\.venv
SC_Universal_Research_Engine_v1\.venv\Scripts\python.exe -m pip install -r SC_Universal_Research_Engine_v1\requirements.txt
.\AVVIA_DASHBOARD.ps1
```

Test: `SC_Universal_Research_Engine_v1\.venv\Scripts\python.exe -m unittest discover -s SC_Universal_Research_Engine_v1/tests -q`.

Il server ascolta solo su loopback, con token sulle operazioni di scrittura. Questa versione è un laboratorio offline e non invia ordini live.

## Protezione delle risorse

Una ricerca web alla volta, priorità Windows inferiore al normale e riserva predefinita di 4 GiB di RAM disponibile prima di partire e tra i blocchi/trial. Per la campagna PRIMARY_GRID_20261013, con Sierra chiuso, la riserva esplicita e 3 GiB (configurazione memory_reserve_gib). Il worker può rilasciare le proprie pagine di cache residenti; se la riserva non torna disponibile la ricerca si arresta. Il controllo è periodico, non un tetto hardware istantaneo: non garantisce che altre applicazioni non si blocchino. Annulla ricerca termina anche i processi figli del launcher Python Windows.
