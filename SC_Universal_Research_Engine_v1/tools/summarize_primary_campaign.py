"""Report exhaustive coverage and training-only weight comparisons."""
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from research_grid import WEIGHTS
from robust_optimizer import save_json,save_csv

PROJECT=Path(__file__).resolve().parents[1]


def summarize(folder):
    folder=Path(folder);campaign=json.loads((folder/'CAMPAIGN.json').read_text())
    lines=['# Prima griglia TO: NQ ed ES','',f"Stato campagna: **{campaign['status']}**.",'',
           'Griglia esaustiva sui valori dichiarati in PLAN.json. Ricerca esplorativa: i periodi finali erano gia stati consultati in altre ricerche. Nessuna stima indipendente definitiva dell\'edge.','',
           '| Ricerca | Configurazioni | Valutazioni train | WF netto USD | Finale netto USD | Trade finale | Secondi |',
           '|---|---:|---:|---:|---:|---:|---:|']
    details=[]
    for row in campaign['jobs']:
        job=PROJECT/'dashboard_jobs'/row['id']
        if not (job/'SUMMARY.json').exists():continue
        s=json.loads((job/'SUMMARY.json').read_text());profiles=defaultdict(list);best={};coverage=defaultdict(set)
        with (job/'TRIALS.csv').open(encoding='utf-8-sig',newline='') as f:
            for trial in csv.DictReader(f):
                stage=int(trial['stage']);p=json.loads(trial['params']);score=float(trial['objective'])
                key=tuple(p['i:'+k] for k in WEIGHTS)
                coverage[stage].add(tuple(sorted(p.items())))
                if not trial['invalid'] and score>-1e30:
                    profiles[(stage,key)].append((score,float(trial['net'])))
                    if stage not in best or score>best[stage]['objective']:
                        best[stage]=dict(stage=stage,objective=score,net=float(trial['net']),trades=int(trial['trades']),params=p)
        counts={stage:len(v) for stage,v in coverage.items()}
        if len(counts)!=4 or any(v!=s['total_combinations'] for v in counts.values()):
            raise ValueError(f"Griglia incompleta o duplicata: {row['label']} {counts}")
        ranking=[]
        for (stage,weights),values in profiles.items():
            ranking.append(dict(stage=stage,weights='-'.join(str(v) for v in weights),valid_configurations=len(values),
                                best_training_objective=max(v[0] for v in values),
                                median_training_net=statistics.median(v[1] for v in values)))
        save_csv(job/'WEIGHT_COMPARISON_TRAIN_ONLY.csv',sorted(ranking,key=lambda x:(x['stage'],-x['best_training_objective'])))
        save_json(job/'GRID_COVERAGE.json',dict(exhaustive=True,unique_per_stage=counts,expected_per_stage=s['total_combinations']))
        save_json(job/'STAGE_SELECTIONS.json',list(best.values()))
        lines.append(f"| {row['label']} | {s['total_combinations']:,} | {s['trials_run']:,} | {sum(f['net'] for f in s['walk_forward']):,.2f} | {s['holdout']['net']:,.2f} | {s['holdout']['n']} | {s['elapsed_seconds']:.1f} |")
        profile='-'.join(str(s['params']['i:'+k]) for k in WEIGHTS)
        details.extend(['',f"## {row['label']}",'',f"Pesi scelti sul development (assorbimento, trapped, delta, imbalance): **{profile}**. Nessuna scelta basata sul profitto finale.",
            f"Audit: {s['tick_audit']['walk_forward_trades']+s['tick_audit']['holdout_trades']} trade, {s['tick_audit']['ticks']:,} tick; corrispondenza verificata con il simulatore scalare.",
            f"Giornate disponibili: {len(s['development_days'])+len(s['holdout_days'])}. Job dashboard: `{row['id']}`."])
        for m in s['datasets']:
            if m.get('excluded_trade_dates'):details.append('Date mancanti escluse: '+', '.join(m['excluded_trade_dates'])+'.')
        for exclusion in s.get('data_exclusions',[]):details.append('Contratto escluso: '+exclusion['source']+'; '+exclusion['start']+' - '+exclusion['end']+'.')
    lines+=details+['','SL/TP in tick, costi e slippage inclusi. Il confronto tra pesi e in WEIGHT_COMPARISON_TRAIN_ONLY.csv: descrive soltanto l\'addestramento, non prova che un rapporto sia superiore fuori campione.',
                    'Tutti i trade chiudono entro 16:55 America/New_York. I livelli Deluxe causali restano da riconciliare con Sierra. Fills da LAST; nessuna simulazione della coda ordini.']
    (folder/'RISULTATI.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(str((folder/'RISULTATI.md').resolve()))


if __name__=='__main__':summarize(sys.argv[1])
