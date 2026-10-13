"""Describe all declared sessions; no session is promoted based on final profit."""
import csv
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def summarize(root):
    folder=root/'output/SESSION_STOP_GRID_20261013'
    campaign=json.loads((folder/'CAMPAIGN.json').read_text())
    if campaign['status']!='complete':raise ValueError('Campagna non ancora completa')
    rows=[];audited=0;ticks=0
    for job in campaign['jobs']:
        source=root/'dashboard_jobs'/job['id']
        s=json.loads((source/'SUMMARY.json').read_text());c=json.loads((source/'config.json').read_text())
        with (source/'TRIALS.csv').open(encoding='utf-8-sig',newline='') as f:trials=list(csv.DictReader(f))
        for stage in sorted({r['stage'] for r in trials}):
            selected=[r for r in trials if r['stage']==stage]
            assert len(selected)==c['trials']==len({json.dumps(json.loads(r['params']),sort_keys=True) for r in selected})
        for filename in ('WF_TRADES.csv','HOLDOUT_TRADES.csv'):
            with (source/filename).open(encoding='utf-8-sig',newline='') as f:trades=list(csv.DictReader(f))
            for trade in trades:
                assert trade['tick_audit_verified']=='True'
                entry=datetime.fromisoformat(trade['entry_utc']).replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('America/New_York'))
                exit=datetime.fromisoformat(trade['exit_utc']).replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('America/New_York'))
                seconds=entry.hour*3600+entry.minute*60+entry.second+entry.microsecond/1e6
                assert not c['entry_windows'] or any(a<=seconds<b for a,b in c['entry_windows'])
                cutoff=datetime.fromisoformat(trade['day']+'T16:55:00').replace(tzinfo=ZoneInfo('America/New_York'))
                session_start=cutoff.replace(hour=18,minute=0)-timedelta(days=1)
                assert session_start<=entry<=exit<=cutoff
                audited+=1;ticks+=int(trade['ticks_audited'])
        initial=[r for r in trials if r['stage']=='1' and not r['invalid']]
        p=s['params']
        with (source/'HOLDOUT_TRADES.csv').open(encoding='utf-8-sig',newline='') as f:exits=Counter(r['exit_reason'] for r in csv.DictReader(f))
        rows.append(dict(label=job['label'],configurations=c['trials'],train_initial_positive=sum(float(r['net'])>0 for r in initial),train_initial_admissible=len(initial),
                         wf_n=sum(f['n'] for f in s['walk_forward']),wf_net=sum(f['net'] for f in s['walk_forward']),
                         wf_insufficient_folds=sum(f['sample_status']=='insufficient_sample' for f in s['walk_forward']),
                         final_n=s['holdout']['n'],final_net=s['holdout']['net'],final_sample=s['holdout']['sample'],
                         stress=s['stress_extra_2_ticks_net'],min_agg=p['i:min_agg'],imbalance_volume=p['i:imbalance_volume'],
                         sl=p['e:sl'],tp=p['e:tp'],score=p['e:min_score'],trailing=p['e:trailing'],be_trigger=p['e:be_trigger'],
                         exits=dict(exits)))
    result=dict(rows=rows,verified_trades=audited,verified_ticks=ticks,unique_configurations=sum(r['configurations'] for r in rows))
    (folder/'SESSION_STOP_SUMMARY.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    lines=['# TO: orari, soglie e gestione stop', '',
           'Ricerca esplorativa su dati già consultati. La sessione è un asse sperimentale: nessuna sessione viene scelta automaticamente dal finale.',
           'ALL = giornata completa; RTH = 09:30–16:00; AM = 09:30–12:00; PM = 12:00–16:00 New York. Sono finestre degli ingressi effettivi; le posizioni già aperte restano soggette a stop, target, durata 30 minuti e chiusura 16:55.',
           'Stop e target in tick. NQ: SL 24/56/112, TP 68/136; ES: SL 8/16/32, TP 16/32.',
           'NQ: volume aggressivo 10/40/80, volume minimo imbalance 5/20; ES: 150/400/800 e 50/150/300. Sono contratti scambiati al livello, non numero di ordini.',
           'BE: attivazione 40 tick e offset 3 NQ; 12 tick e offset 2 ES. Trailing: distanza 48/attivazione 64 NQ, 12/20 ES. Ogni gestione è confrontata con la sua disattivazione.',
           'Struttura TO e pesi 4-0-1-1 fissi. Nessun filtro Deluxe in questa campagna, per isolare orari, soglie e gestione.',
           'Screening train: almeno 100 trade, 20 giorni attivi, 20 trade per ciascuno dei tre blocchi. Campione di valutazione: almeno 50 trade e 15 giorni attivi; non è una prova di significatività.', '',
           '| Test | Trade WF | Netto WF $ | Fold insufficienti | Trade finale | Netto finale $ | Stress $ | SL/TP | BE | Trailing |',
           '|---|---:|---:|---:|---:|---:|---:|---|---:|---:|']
    lines += [f"| {r['label']} | {r['wf_n']} | {r['wf_net']:.2f} | {r['wf_insufficient_folds']} | {r['final_n']} | {r['final_net']:.2f} | {r['stress']:.2f} | {r['sl']}/{r['tp']} | {r['be_trigger']} | {r['trailing']} |" for r in rows]
    lines += ['',f'Verifica: {audited} trade, {ticks} tick auditati; copertura completa della griglia per ogni fase, ingressi dentro le finestre e tutte le uscite entro 16:55 New York.',
              'Le soglie volume non richiedono necessariamente assorbimento nel segnale: gli altri componenti TO possono superare lo score anche quando il componente assorbimento è zero.',
              'Restano le esclusioni SCID delle campagne V2 e la parità Sierra non completa. I migliori parametri riportati sono scelti sul train, non sul finale.']
    (folder/'RISULTATI_ORARI_STOP.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':summarize(Path(__file__).resolve().parents[1])
