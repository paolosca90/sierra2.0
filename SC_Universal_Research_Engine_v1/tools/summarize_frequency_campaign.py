"""Compare sample breadth V1/V2 without selecting on final performance."""
import csv
import json
import sys
from pathlib import Path
from summarize_primary_campaign import summarize,PROJECT
from robust_optimizer import save_json


def report(folder):
    folder=Path(folder);summarize(folder)
    campaign=json.loads((folder/'CAMPAIGN.json').read_text())
    old=json.loads((PROJECT/'output/PRIMARY_GRID_20261013/FINAL_VERIFICATION.json').read_text())['checks']
    lines=['# Griglie per strumento: ampiezza del campione V2','',
        'La griglia e specifica per NQ ed ES e usa scale congelate sul primo train. Nessuna quota giornaliera viene forzata. I segmenti finali erano gia noti: ricerca esplorativa.','',
        '| Modello | Trade WF V1 → V2 | Trade finali V1 → V2 | Giorni attivi finali V2 | Netto finale V2 USD | Screening finale |',
        '|---|---:|---:|---:|---:|---|']
    results=[]
    for row in campaign['jobs']:
        if row['status']!='complete':continue
        job=PROJECT/'dashboard_jobs'/row['id'];s=json.loads((job/'SUMMARY.json').read_text())
        label=row['label'].replace(' V2','');baseline=next(x for x in old if x['label']==label)
        before=json.loads((PROJECT/'dashboard_jobs'/baseline['job']/'SUMMARY.json').read_text())
        quality=s['sample_quality']['final'];wf=sum(f['n'] for f in s['walk_forward'])
        item=dict(label=label,job=row['id'],old_wf=sum(f['n'] for f in before['walk_forward']),new_wf=wf,
                  old_final=before['holdout']['n'],new_final=s['holdout']['n'],active_days=s['holdout']['sample']['active_days'],
                  final_net=s['holdout']['net'],wf_net=sum(f['net'] for f in s['walk_forward']),sample=quality,
                  fold_samples=[dict(fold=f['fold'],trades=f['n'],active_days=f['active_days'],status=f['sample_status']) for f in s['walk_forward']],
                  tick_audit=s['tick_audit'],params=s['params'],seconds=s['elapsed_seconds'])
        results.append(item)
        status='Ampiezza sufficiente' if quality['sufficient'] else 'INSUFFICIENTE'
        lines.append(f"| {label} | {item['old_wf']} → {wf} | {item['old_final']} → {item['new_final']} | {item['active_days']} | {item['final_net']:,.2f} | {status} |")
        # Independent check that all actual training selections met the declared
        # policy; held-out returns never participate in this check.
        best={}
        with (job/'TRIALS.csv').open(encoding='utf-8-sig',newline='') as f:
            for t in csv.DictReader(f):
                stage=int(t['stage'])
                if float(t['objective'])>-1e30 and (stage not in best or float(t['objective'])>float(best[stage]['objective'])):best[stage]=t
        assert len(best)==4
        c=json.loads((job/'config.json').read_text());selected=[]
        for stage,t in sorted(best.items()):
            blocks=json.loads(t['block_trades']);active=int(t['active_days']);n=int(t['trades'])
            assert n>=c['min_trades'] and active>=c['min_active_days'] and min(blocks)>=c['min_trades_per_training_block']
            selected.append(dict(stage=stage,trades=n,active_days=active,block_trades=blocks))
        save_json(job/'TRAINING_SAMPLE_VERIFICATION.json',dict(passed=True,selections=selected))
    lines+=['','I conteggi finali riguardano solo l\'ultimo 20% disponibile: 77 trade date NQ e 65 ES. Il WF comprende tre finestre successive; i parametri possono cambiare a ogni refit. Non sommare i trade dei diversi modelli come se fossero un portafoglio.','',
             'Ampiezza sufficiente significa soltanto che sono superati i limiti preregistrati di 50 trade e 15 giorni attivi. Non certifica significativita, indipendenza dei trade o un edge. Il train ha richiesto almeno 200 trade, 30 giorni attivi e 40 trade per sotto-periodo.','',
             'Dati originali -CME; sei date NQ ed ESM26 non validi restano esclusi. Chiusura entro 16:55 New York. Parita dei livelli con Sierra ancora da completare.']
    (folder/'CONFRONTO_CAMPIONE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save_json(folder/'SAMPLE_COMPARISON.json',dict(status=campaign['status'],models=results))
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':report(sys.argv[1])
