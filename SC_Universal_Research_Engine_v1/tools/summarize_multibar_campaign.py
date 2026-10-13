"""Coverage and tick/session checks for the declared multibar search."""
import csv
import json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from summarize_primary_campaign import summarize as coverage_report


def summarize(root):
    folder=root/'output/MULTIBAR_GRID_20261013'
    campaign=json.loads((folder/'CAMPAIGN.json').read_text())
    coverage_report(folder)
    rows=[];trade_count=0;tick_count=0
    for job in campaign['jobs']:
        source=root/'dashboard_jobs'/job['id']
        if not (source/'SUMMARY.json').exists():continue
        s=json.loads((source/'SUMMARY.json').read_text());c=json.loads((source/'config.json').read_text())
        stage=json.loads((source/'STAGE_SELECTIONS.json').read_text())
        wf=s['walk_forward'];final=s['holdout'];p=s['params'];audit=s['tick_audit']
        models=[{'days':(f['test_first'],f['test_last']),'params':next(x['params'] for x in stage if x['stage']==f['fold'])} for f in wf if f.get('n')]
        for file in ('WF_TRADES.csv','HOLDOUT_TRADES.csv'):
            with (source/file).open(encoding='utf-8-sig',newline='') as stream:trades=list(csv.DictReader(stream))
            previous=None
            for t in trades:
                assert t['tick_audit_verified']=='True'
                entry=datetime.fromisoformat(t['entry_utc']).replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('America/New_York'))
                exit=datetime.fromisoformat(t['exit_utc']).replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('America/New_York'))
                cutoff=datetime.fromisoformat(t['day']+'T16:55:00').replace(tzinfo=ZoneInfo('America/New_York'))
                assert cutoff.replace(hour=18,minute=0)-timedelta(days=1)<=entry<=exit<=cutoff
                if previous:assert previous<entry
                previous=exit
                selected=p if file=='HOLDOUT_TRADES.csv' else next(m['params'] for m in models if m['days'][0]<=t['day']<=m['days'][1])
                mode=int(selected.get('e:session_mode',0));seconds=entry.hour*3600+entry.minute*60+entry.second+entry.microsecond/1e6
                window={1:(34200,57600),2:(34200,43200),3:(43200,57600)}.get(mode)
                assert window is None or window[0]<=seconds<window[1]
                trade_count+=1;tick_count+=int(t['ticks_audited'])
        for selection in stage:
            assert selection['trades']>=c['min_trades']
        rows.append(dict(label=job['label'],job_id=job['id'],instrument=c['instrument'],
                         bar_seconds=c['bar_seconds'],trades_per_bar=c.get('trades_per_bar',0),
                         configurations=s['total_combinations'],training_evaluations=s['trials_run'],
                         wf_n=sum(f['n'] for f in wf),wf_net=sum(f['net'] for f in wf),
                         wf_insufficient=sum(f.get('sample_status')!='sufficient_for_screening' for f in wf),
                         final_n=final['n'],final_net=final['net'],final_pf=final['pf'],
                         final_sample=s['sample_quality']['final'],stress=s['stress_extra_2_ticks_net'],
                         days=len(s['development_days'])+len(s['holdout_days']),params=p,
                         elapsed_seconds=s['elapsed_seconds'],audit_trades=audit['holdout_trades']+audit['walk_forward_trades'],
                         audit_ticks=audit['ticks'],uncertainty=s['uncertainty'],data_exclusions=s.get('data_exclusions',[])))
    result=dict(status=campaign['status'],rows=rows,unique_parameter_combinations=sum(r['configurations'] for r in rows),
                training_evaluations=sum(r['training_evaluations'] for r in rows),audited_trades=trade_count,audited_ticks=tick_count)
    (folder/'MULTIBAR_SUMMARY.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    lines=['# Ricerca TO estesa: tempo e numero di trade', '',
           f"Stato: {campaign['status']}. Griglie complete per ogni blocco terminato. La scelta dei parametri avviene sul train; i risultati dei diversi blocchi restano tutti visibili.",
           'Barre tempo: 15/30/60/120/300 secondi. Barre trade: NQ 500/2000, ES 2000/10000 esecuzioni SCID. Segnale sulla barra completata; esecuzioni, stop e uscite sui tick reali. Barre trade incomplete scartate, reset a 18:00 NY e dopo gap >90 secondi.',
           'Nessuna valutazione intrabar del TO ancora in formazione. Nessuna simulazione delle code del book. La parità native Sierra rimane da verificare sulle nuove aggregazioni.',
           'Per ogni aggregazione: tre volumi minimi, due imbalance ratio, estremo richiesto sì/no, sei profili di pesi, tre SL, tre TP, due score, quattro finestre di ingresso. Volume imbalance e lookback sono fissati per aggregazione; trailing e BE disattivati in questa fase. Periodo gennaio 2025–settembre 2026 disponibile, rollout volume e raw -CME.',
           '72.576 combinazioni di parametri dichiarate. I profili con peso zero possono produrre segnali equivalenti per valori di componenti inutilizzati: non sono 72.576 strategie economicamente indipendenti.', '',
           '| Modello | Trade WF | Netto WF USD | Fold insufficienti | Trade finale | Netto finale USD | Stress USD | Sessione finale |',
           '|---|---:|---:|---:|---:|---:|---:|---|']
    sessions={0:'ALL',1:'RTH',2:'AM',3:'PM'}
    for r in rows:lines.append(f"| {r['label']} | {r['wf_n']} | {r['wf_net']:.2f} | {r['wf_insufficient']} | {r['final_n']} | {r['final_net']:.2f} | {r['stress']:.2f} | {sessions[int(r['params']['e:session_mode'])]} |")
    lines += ['', '## Verifiche e interpretazione', '',
              f"Completate {result['unique_parameter_combinations']} combinazioni e {result['training_evaluations']} valutazioni train. Audit indipendente: {trade_count} trade, {tick_count} tick; ingressi nelle finestre selezionate e uscite entro 16:55 NY.",
              'Le date sono già state consultate: tutti i risultati sono esplorativi. Scegliere il miglior timeframe dal finale consuma ulteriormente il campione e richiede nuova validazione. Un singolo blocco positivo non dimostra edge robusto.',
              'Copertura da verifiche SCID, senza interpolazione o normalizzazione. Il periodo ESM26 non ordinato e sei giornate NQ mancanti restano esclusi ove segnalati nel relativo job.']
    (folder/'RISULTATI_MULTIBAR.md').write_text('\n'.join(lines),encoding='utf-8')
    if campaign['status']=='complete':(root/'docs/RICERCA_MULTIBAR_20261013.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],completed=len(rows),combinations=result['unique_parameter_combinations'],
                          audited_trades=trade_count,audited_ticks=tick_count),indent=2))
    return result


if __name__=='__main__':summarize(Path(__file__).resolve().parents[1])
