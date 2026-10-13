# Sierra 2.0

Motore locale di ricerca e backtest per Sierra Chart, con dashboard web,
lettura dei dati SCID e ottimizzazione di indicatori e gestione della posizione.

## Avvio

Seguire [README_DASHBOARD.md](README_DASHBOARD.md) per installazione e utilizzo.
La dashboard si avvia con `AVVIA_DASHBOARD.cmd` su Windows.
I dati Sierra, le cache e i risultati delle campagne restano locali e non sono inclusi nel repository.

## Componenti

- `SC_Universal_Research_Engine_v1`: dashboard, motore Python, ottimizzatore, test e sorgenti ACSIL.
- `StrategyOptimizer_Universal`: ottimizzatore replay legacy con licenza e riferimenti upstream conservati.
- `TO_Deluxe_Levels.cpp` e `UniversalSignalTrader.cpp`: sorgenti ACSIL.
- [AUDIT_RICERCA.md](AUDIT_RICERCA.md): verifiche, risultati e limiti della ricerca.

Il motore offline simula esecuzioni sui trade registrati: non riproduce code di esecuzione
o fill reali. La riconciliazione completa con Sierra e l'esistenza di un vantaggio operativo
non sono ancora dimostrate. Gli indicatori ACSIL arbitrari richiedono un adattatore per il motore offline.

Le licenze e le attribuzioni dei componenti di terze parti restano applicabili.
