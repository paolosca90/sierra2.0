# TO: orari, soglie e gestione stop

Ricerca esplorativa su dati già consultati. La sessione è un asse sperimentale: nessuna sessione viene scelta automaticamente dal finale.
ALL = giornata completa; RTH = 09:30–16:00; AM = 09:30–12:00; PM = 12:00–16:00 New York. Sono finestre degli ingressi effettivi; le posizioni già aperte restano soggette a stop, target, durata 30 minuti e chiusura 16:55.
Stop e target in tick. NQ: SL 24/56/112, TP 68/136; ES: SL 8/16/32, TP 16/32.
NQ: volume aggressivo 10/40/80, volume minimo imbalance 5/20; ES: 150/400/800 e 50/150/300. Sono contratti scambiati al livello, non numero di ordini.
BE: attivazione 40 tick e offset 3 NQ; 12 tick e offset 2 ES. Trailing: distanza 48/attivazione 64 NQ, 12/20 ES. Ogni gestione è confrontata con la sua disattivazione.
Struttura TO e pesi 4-0-1-1 fissi. Nessun filtro Deluxe in questa campagna, per isolare orari, soglie e gestione.
Screening train: almeno 100 trade, 20 giorni attivi, 20 trade per ciascuno dei tre blocchi. Campione di valutazione: almeno 50 trade e 15 giorni attivi; non è una prova di significatività.

| Test | Trade WF | Netto WF $ | Fold insufficienti | Trade finale | Netto finale $ | Stress $ | SL/TP | BE | Trailing |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| NQ V3 TO stops ALL | 383 | -9795.00 | 0 | 103 | -3650.00 | -4680.00 | 56/68 | 40 | 0 |
| NQ V3 TO stops RTH | 141 | -2775.00 | 2 | 28 | 425.00 | 145.00 | 56/68 | 40 | 0 |
| NQ V3 TO stops AM | 98 | 335.00 | 3 | 35 | 4170.00 | 3820.00 | 112/68 | 0 | 0 |
| NQ V3 TO stops PM | 112 | -1065.00 | 2 | 22 | 655.00 | 435.00 | 56/68 | 40 | 0 |
| ES V3 TO stops ALL | 166 | -9267.50 | 1 | 74 | -2220.00 | -4070.00 | 8/32 | 12 | 12 |
| ES V3 TO stops RTH | 105 | -2575.00 | 2 | 33 | -1690.00 | -2515.00 | 8/16 | 0 | 0 |
| ES V3 TO stops AM | 86 | -2555.00 | 3 | 28 | -1890.00 | -2590.00 | 32/16 | 12 | 0 |
| ES V3 TO stops PM | 79 | -3345.00 | 3 | 23 | -827.50 | -1402.50 | 8/16 | 12 | 0 |

Verifica: 1516 trade, 8842668 tick auditati; copertura completa della griglia per ogni fase, ingressi dentro le finestre e tutte le uscite entro 16:55 New York.
Le soglie volume non richiedono necessariamente assorbimento nel segnale: gli altri componenti TO possono superare lo score anche quando il componente assorbimento è zero.
Restano le esclusioni SCID delle campagne V2 e la parità Sierra non completa. I migliori parametri riportati sono scelti sul train, non sul finale.

## Interpretazione

NQ AM è l’unica finestra con walk-forward positivo (+335 USD su 98 trade), ma tutti e tre i fold hanno meno di 50 trade. Lo stress di due tick aggiuntivi per trade riduce questo totale a -645 USD. Il finale +4170 USD su 35 trade è già consultato e sotto la soglia di screening.

ES resta negativo in tutte le finestre, con soglie molto maggiori di NQ. L’allargamento degli stop e le gestioni testate non dimostrano un vantaggio. Nessuna conclusione universale su TO o su gestioni non testate.
