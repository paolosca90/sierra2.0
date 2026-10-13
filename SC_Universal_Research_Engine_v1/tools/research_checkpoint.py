"""Append-only trial journal; reuse only with identical model, data and experiment."""
import atexit
import hashlib
import json
from pathlib import Path


class TrialCheckpoint:
    def __init__(self,folder,identity):
        folder=Path(folder);self.path=folder/'TRIAL_CHECKPOINT.jsonl';self.rows={}
        fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        meta=folder/'CHECKPOINT_IDENTITY.json'
        if meta.exists():
            old=json.loads(meta.read_text())
            if old['sha256']!=fingerprint:raise ValueError('Checkpoint incompatibile: codice, dati o parametri cambiati; creare una nuova ricerca')
        else:meta.write_text(json.dumps(dict(sha256=fingerprint,identity=identity),indent=2),encoding='utf-8')
        if self.path.exists():
            valid_bytes=0
            with self.path.open('rb') as source:
                for line in source:
                    if not line.endswith(b'\n'):break
                    row=json.loads(line);key=(row['stage'],row['trial'])
                    if key in self.rows:raise ValueError('Trial duplicato nel checkpoint')
                    self.rows[key]=row;valid_bytes+=len(line)
            # Interrupted trailing write is never treated as a completed trial.
            with self.path.open('r+b') as source:source.truncate(valid_bytes)
        self.stream=self.path.open('a',encoding='utf-8');self.pending=0
        atexit.register(self.close)

    def append(self,row):
        key=(row['stage'],row['trial'])
        if key in self.rows:raise ValueError('Trial gia registrato')
        self.stream.write(json.dumps(row)+'\n');self.rows[key]=row;self.pending+=1
        if self.pending>=25:self.stream.flush();self.pending=0

    def close(self):
        if not self.stream.closed:self.stream.flush();self.stream.close()
