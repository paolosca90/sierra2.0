# Ricerca TO estesa: tempo e numero di trade

Stato: complete. Griglie complete per ogni blocco terminato. La scelta dei parametri avviene sul train; i risultati dei diversi blocchi restano tutti visibili.
Barre tempo: 15/30/60/120/300 secondi. Barre trade: NQ 500/2000, ES 2000/10000 esecuzioni SCID. Segnale sulla barra completata; esecuzioni, stop e uscite sui tick reali. Barre trade incomplete scartate, reset a 18:00 NY e dopo gap >90 secondi.
Nessuna valutazione intrabar del TO ancora in formazione. I fill usano ultimo prezzo scambiato e slippage, non il bid/ask nativo. Nessuna simulazione delle code del book. La parità nativa Sierra rimane da verificare sulle nuove aggregazioni.
Per ogni aggregazione: tre volumi minimi, due imbalance ratio, estremo richiesto sì/no, sei profili di pesi, tre SL, tre TP, due score, quattro finestre di ingresso. Volume imbalance e lookback sono fissati per aggregazione; trailing e BE disattivati in questa fase. Periodo gennaio 2025–settembre 2026 disponibile, rollover volume e raw -CME.
72.576 combinazioni di parametri dichiarate. I profili con peso zero possono produrre segnali equivalenti per valori di componenti inutilizzati: non sono 72.576 strategie economicamente indipendenti.

| Modello | Trade WF | Netto WF USD | Fold insufficienti | Trade finale | Netto finale USD | Stress USD | Sessione finale |
|---|---:|---:|---:|---:|---:|---:|---|
| NQ V4 TO 300s | 1143 | 2985.00 | 1 | 1643 | -61025.00 | -77455.00 | AM |
| ES V4 TO 300s | 150 | -6950.00 | 1 | 53 | 2285.00 | 960.00 | PM |
| NQ V4 TO 120s | 567 | -11335.00 | 1 | 44 | -290.00 | -730.00 | AM |
| ES V4 TO 120s | 125 | -4025.00 | 3 | 55 | -2287.50 | -3662.50 | ALL |
| NQ V4 TO 2000 trades | 694 | -26775.00 | 0 | 220 | -3350.00 | -5550.00 | ALL |
| ES V4 TO 10000 trades | 155 | -550.00 | 1 | 81 | -2517.50 | -4542.50 | PM |
| NQ V4 TO 500 trades | 1074 | -25025.00 | 1 | 105 | 2700.00 | 1650.00 | ALL |
| ES V4 TO 2000 trades | 207 | -8972.50 | 0 | 21 | 170.00 | -355.00 | PM |
| NQ V4 TO 60s | 969 | 4855.00 | 0 | 787 | 48070.00 | 40200.00 | AM |
| ES V4 TO 60s | 115 | -5512.50 | 2 | 34 | -1632.50 | -2482.50 | RTH |
| NQ V4 TO 30s | 733 | -26060.00 | 0 | 32 | 780.00 | 460.00 | AM |
| ES V4 TO 30s | 184 | -5682.50 | 1 | 20 | -1987.50 | -2487.50 | PM |
| NQ V4 TO 15s | 2167 | -47475.00 | 0 | 243 | 6320.00 | 3890.00 | AM |
| ES V4 TO 15s | 131 | -6267.50 | 1 | 14 | -1232.50 | -1582.50 | RTH |

## Verifiche e interpretazione

Completate 72576 combinazioni e 290304 valutazioni train. Audit indipendente: 11766 trade, 113481126 tick; ingressi nelle finestre selezionate e uscite entro 16:55 NY.
Le date sono già state consultate: tutti i risultati sono esplorativi. Scegliere il miglior timeframe dal finale consuma ulteriormente il campione e richiede nuova validazione. Un singolo blocco positivo non dimostra edge robusto.
Copertura da verifiche SCID, senza interpolazione o normalizzazione. Il periodo ESM26 non ordinato e sei giornate NQ mancanti restano esclusi ove segnalati nel relativo job.

## Candidata esplorativa: NQ V4 TO 60s

Finale: 787 trade, 48070.00 USD; PF 1.1776. Dopo aver rimosso le cinque giornate migliori: 20265.00 USD.
WF complessivo: 4855.00 USD; con due tick aggiuntivi per trade: -4835.00 USD. Ogni fold seleziona parametri propri sul suo train: questo non è il risultato della stessa configurazione fissa in tutti i fold.
Parametri finali scelti sul development: {"i:min_agg": 200, "i:min_pct": 3, "i:level_multiple": 1.5, "i:diagonal": 1.0, "i:imbalance": 4, "i:extreme_ticks": 6, "i:rejection_ticks": 3, "i:close_through": 0.0, "i:bubbles": 2.0, "i:separation": 3.0, "i:trap_buffer": 2.0, "i:min_trapped": 0.0, "i:imbalance_volume": 20, "i:lookback": 15, "i:require_extreme": 0, "i:tolerance": 3, "i:volume_weight": 1.0, "i:sensitivity": 4, "i:w_abs": 4, "i:w_trap": 1, "i:w_delta": 1, "i:w_imb": 1, "e:sl": 112, "e:tp": 240, "e:min_score": 0.3, "e:trailing": 0, "e:trail_trigger": 20, "e:be_trigger": 0, "e:be_offset": 0, "e:quantity": 1, "e:session_mode": 2}
Verificati 787 segnali pubblicati contro la formula offline originale. Componente maggiore in valore assoluto: {"trapped": 785, "absorption": 2}. Contributo netto assorbimento zero in 784 segnali; può includere assorbimenti opposti che si compensano. Non è una verifica dei fill nativi di Sierra.