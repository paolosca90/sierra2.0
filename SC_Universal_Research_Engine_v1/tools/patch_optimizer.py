#!/usr/bin/env python3
"""Patch pinned third-party ACSIL optimizer *copy* safely; fail closed on unknown source."""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path


def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1: raise ValueError(f'{label}: pattern count={n}, expected 1; no changes written')
    return s.replace(old,new,1)


def patch(repo:Path)->dict[str,str]:
    cg=repo/'CombinationGenerator.cpp'
    cm=repo/'ConfigManager.cpp'
    helper=repo/'StrategyOptimizerHelpers.cpp'
    files=[cg,cm,helper]
    source={p:p.read_text(encoding='utf-8-sig') for p in files}
    a=source[cg]
    a=once(a,'std::vector<InputConfig> varyingParams;\n        for (const auto &p : params)\n        {\n            if (std::fabs(p.Increment) > 1e-9)\n            {\n                varyingParams.push_back(p);\n            }\n        }',
           'std::vector<InputConfig> varyingParams = params; // Fixed parameters are applied too.', 'keep fixed params')
    a=once(a,'if (p.Increment > 0)\n            {\n                for (double i = p.MinValue;',
           'if (std::fabs(p.Increment) < 1e-9)\n            {\n                values.push_back(p.MinValue);\n            }\n            else if (p.Increment > 0)\n            {\n                for (double i = p.MinValue;', 'fixed singleton')
    a=once(a,'size_t k = varyingParams.size() - 1;\n            while (k >= 0)',
           'int k = static_cast<int>(varyingParams.size()) - 1;\n            while (k >= 0)', 'fix unsigned underflow')
    source[cg]=a
    a=source[cm]
    a=once(a,'                if (input.contains("increment") && input["increment"].get<double>() == 0)\n                {\n                    continue;\n                }\n\n',
           '                // Fixed inputs increment == 0 must be applied, not silently skipped.\n', 'parse fixed values')
    source[cm]=a
    a=source[helper]
    a=once(a,'int inputIndex = 0;\n        while (true)',
           'int inputIndex = 0;\n        while (inputIndex < 128)', 'enumerate input holes')
    a=once(a,'if (inputName.IsEmpty())\n            {\n                break;\n            }',
           'if (inputName.IsEmpty())\n            {\n                ++inputIndex;\n                continue;\n            }','skip input hole')
    a=once(a,'{"clearExistingTradeSimulationDataForSymbolAndTradeAccount", 1}};',
           '{"clearExistingTradeSimulationDataForSymbolAndTradeAccount", 1},\n            {"skipEmptyPeriods", 1}};', 'generated JSON parser compatibility')
    source[helper]=a
    # All replacements must succeed before writing ANY file.
    timestamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    manifest={}
    for p in files:
        b=p.with_name(p.name+'.before_universal_'+timestamp+'.bak')
        b.write_bytes(p.read_bytes())
        manifest[p.name]=str(b)
        p.write_text(source[p],encoding='utf-8',newline='\n')
    return manifest

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('repo',type=Path)
    args=ap.parse_args()
    try:
        print('Patched:',patch(args.repo.resolve()))
    except Exception as e:
        raise SystemExit('STOP - no patches applied (or check backups): '+str(e))
