"""Descriptive analysis of frozen published trades; never selects new parameters."""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def analyze(campaign, jobs, output):
    results = []
    for job in json.loads(campaign.read_text(encoding='utf-8'))['jobs']:
        folder = jobs / job['id']
        config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
        commission = float(config['commission'])
        for stage, filename in [('walk_forward', 'WF_TRADES.csv'), ('final_reused', 'HOLDOUT_TRADES.csv')]:
            with (folder / filename).open(encoding='utf-8-sig', newline='') as stream:
                trades = list(csv.DictReader(stream))
            groups = defaultdict(list)
            for trade in trades:
                net = float(trade['net_usd'])
                quantity = int(trade['quantity'])
                filled_gross = (float(trade['exit_fill']) - float(trade['entry_fill'])) * int(trade['side']) * quantity * (20 if config['instrument'] == 'NQ' else 50)
                assert abs(filled_gross - commission * quantity - net) < 1e-6
                assert trade['tick_audit_verified'] == 'True'
                local = datetime.fromisoformat(trade['entry_utc']).replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('America/New_York'))
                minute = local.hour * 60 + local.minute
                session = 'RTH_0930_1600' if 570 <= minute < 960 else 'outside_RTH'
                direction = 'long' if int(trade['side']) == 1 else 'short'
                for group in ['all', session, direction, session + '_' + direction]:
                    groups[group].append((trade['day'], net, commission * quantity))
            for group, values in sorted(groups.items()):
                daily = defaultdict(float)
                for day, net, fee in values:
                    daily[day] += net
                wins = sum(max(net, 0) for _, net, _ in values)
                losses = -sum(min(net, 0) for _, net, _ in values)
                total = sum(daily.values())
                fees = sum(fee for _, _, fee in values)
                results.append(dict(label=job['label'], stage=stage, group=group, n=len(values), active_days=len(daily), net=total,
                                    gross_after_slippage=total + fees, commissions=fees, avg_net=total / len(values),
                                    profit_factor=wins / losses if losses else None,
                                    net_without_best_day=total - max(daily.values()),
                                    positive_months=sum(v > 0 for v in [sum(net for day, net in daily.items() if day.startswith(month)) for month in sorted({day[:7] for day in daily})])))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'EDGE_DIAGNOSTICS.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    lines = ['# TO Reversal: diagnosi descrittiva', '', 'Configurazioni già congelate; nessuna nuova selezione. Finale già riutilizzato: non è un test indipendente.',
             'Lordo = netto + commissioni; mantiene slippage e regole di esecuzione. I sottogruppi sono descrittivi: filtrare gli ingressi richiede un nuovo backtest.', '',
             '| Strategia | Periodo | Gruppo | Trade | Netto USD | Lordo dopo slippage USD | Netto senza giorno migliore USD |',
             '|---|---|---|---:|---:|---:|---:|']
    lines += [f"| {r['label']} | {r['stage']} | {r['group']} | {r['n']} | {r['net']:.2f} | {r['gross_after_slippage']:.2f} | {r['net_without_best_day']:.2f} |" for r in results]
    lines += ['', 'Copertura: SCID canonici -CME disponibili; restano esclusi il periodo ESM26 non ordinato e sei giornate NQ mancanti. Parità completa con Sierra non verificata.']
    (output / 'EDGE_DIAGNOSTICS.md').write_text('\n'.join(lines), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--campaign', type=Path, default=root / 'output/INSTRUMENT_GRID_20261013/CAMPAIGN.json')
    parser.add_argument('--jobs', type=Path, default=root / 'dashboard_jobs')
    parser.add_argument('--output', type=Path, default=root / 'output/TO_EDGE_DIAGNOSTICS_20261013')
    args = parser.parse_args()
    rows = analyze(args.campaign, args.jobs, args.output)
    for row in rows:
        if row['group'] in ('all', 'RTH_0930_1600', 'outside_RTH'):
            print(json.dumps(row))
