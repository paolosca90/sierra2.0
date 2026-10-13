"""Generate a bounded native TO-input search. Never launches Sierra or orders."""
import argparse
import json
from datetime import date
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--instrument',choices=['NQ','ES'],required=True)
    p.add_argument('--train-start',type=date.fromisoformat,required=True)
    p.add_argument('--train-end',type=date.fromisoformat,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.train_end<=args.train_start:
        p.error('train-end must follow train-start')
    if args.out.exists():
        p.error('Output already exists')
    params=[]
    def add(index,name,kind,low,high=None,step=0):
        params.append(dict(_name=name,index=index,type=kind,min=low,max=low if high is None else high,increment=step))
    add(0,'Bullish absorption','bool',1)
    add(1,'Bearish absorption','bool',1)
    floor=20 if args.instrument=='NQ' else 75
    add(2,'Min aggressive volume','int',floor,4*floor,floor)
    add(3,'Min level volume percent','float',8)
    add(4,'Level volume multiple','float',2)
    add(5,'Diagonal imbalance','int',1)
    add(6,'Imbalance ratio','float',2,4,1)
    add(7,'Max ticks from extreme','int',3)
    add(8,'Rejection ticks','int',2)
    add(9,'Close through','bool',0)
    add(10,'Confirmation bars MUST be zero','int',0)
    add(12,'Max absorption levels','int',2)
    add(13,'Min absorption separation','int',3)
    add(28,'Calculate all loaded bars','int',0)
    add(41,'Trap buffer ticks','int',2)
    add(42,'Minimum trapped volume','int',0)
    add(43,'Imbalance min volume','int',20)
    add(59,'Enable markers','bool',1)
    add(60,'Score threshold','float',.3)
    add(61,'Lookback','int',5,15,5)
    add(62,'Require swing extreme','bool',1)
    add(63,'Extreme tolerance ticks','int',1)
    for index,value in [(64,4),(65,1),(66,1),(67,1),(78,4)]:
        add(index,'Score weight/sensitivity','float',value)
    add(68,'Volume weighting','bool',1)
    config=dict(customStudyFileAndFunctionName='TOReversalEngine.scsf_AbsorptionDetector',
        openResultsFolder=False,
        replayConfig=dict(replaySpeed=120,startDate=str(args.train_start),startTime='00:00:00.000',
                          replayMode=3,chartsToReplay=0,clearExistingTradeSimulationDataForSymbolAndTradeAccount=1,
                          skipEmptyPeriods=True),
        logConfig=dict(enableLog=True,enableShowLogOnChart=True,maxLogLines=25),paramConfigs=params)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    instructions=f'''# Native campaign {args.instrument}: 36 combinations

Train only: {args.train_start} through {args.train_end} inclusive.
IMPORTANT: the upstream optimizer has NO end-date field. Set the TEST chart's
Date Range To to {args.train_end} BEFORE starting replay. Without that chart
cutoff this configuration is NOT a train-only experiment. Never run on a live chartbook.

Target study: TO Reversal Engine (not the trader). Uses original sparse input
indices 0..78; verify the InputsFix variant retains this mapping.
Use UniversalSignalTrader on a dedicated empty Sim# account, simulation ON.
Freeze its quantity, stop, target and exits before this campaign. Replay clears
simulation history for that symbol/account. Archive valuable logs first.

This searches min aggressive volume x imbalance ratio x lookback (4x3x3).
Fixed values include Confirmation Bars=0, score threshold=.30, weights=4:1:1:1,
sensitivity=4. These are research ranges, not recommended trading settings.
Ranking from the native optimizer is IN SAMPLE only. Validate the selected
settings on subsequent unseen dates. Do not select settings from the final holdout.

For a causal Deluxe comparison capture a separate V2 CSV from each frozen
candidate in a replay (new filename each time). The native optimizer itself
changes only one study and does NOT jointly optimize all study inputs or export
one V2 collector file per combination automatically.
'''
    args.out.with_suffix('.md').write_text(instructions,encoding='utf-8')
    print(f'Created {args.out}: 36 combinations. Read {args.out.with_suffix(".md")} before replay.')


if __name__=='__main__':
    main()
