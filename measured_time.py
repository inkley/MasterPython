"""Strict measured CSV timing and plot breaks; legacy CSV handling stays separate."""
import csv
import json
from pathlib import Path
import uuid
import numpy as np


def load_measured_time(path, index):
    with Path(path).open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f); rows=list(reader); fields=set(reader.fieldnames or [])
    required={'SessionId','TimeDomainId','AttemptIndex','TriggerTicks','TickHz','TimeBasis','GapBefore','QualityFlags'}
    claims=any(r.get('TimeBasis')=='RAW_TRIGGER_TICKS' for r in rows)
    if not claims and not fields & {'TriggerTicks','TimeDomainId','AttemptIndex'}:
        return None
    if not rows or not required <= fields or len(rows)!=len(index):
        raise ValueError('Incomplete measured timing columns')
    ticks=[];attempts=[];quality=[];gap=[]
    for r in rows:
        if r['TimeBasis']!='RAW_TRIGGER_TICKS':raise ValueError('Mixed measured/nominal time basis')
        ticks.append(int(r['TriggerTicks']));attempts.append(int(r['AttemptIndex']))
        quality.append(int(r['QualityFlags']))
        if r['GapBefore'] not in ('0','1'):raise ValueError('Invalid GapBefore')
        gap.append(r['GapBefore']=='1')
    if len({r['SessionId'] for r in rows})!=1 or len({r['TimeDomainId'] for r in rows})!=1 or len({r['TickHz'] for r in rows})!=1:
        raise ValueError('Mixed recording/domain/clock; analyze separate segments')
    for key in ('SessionId','TimeDomainId'):
        if not uuid.UUID(rows[0][key]).int:raise ValueError('Zero measured identity')
    hz=int(rows[0]['TickHz'])
    if hz!=20000000 or any(not 0<=t<2**64 for t in ticks) or any(not 0<=a<2**32 for a in attempts):
        raise ValueError('Measured tick/attempt range or clock profile')
    if any(q<0 or q>255 for q in quality):raise ValueError('Unknown quality flags')
    if len(set(quality))!=1:raise ValueError('Mixed capture quality flags')
    deltas=[b-a for a,b in zip(ticks,ticks[1:])]
    if any(d<=0 for d in deltas) or any(b<=a for a,b in zip(attempts,attempts[1:])):
        raise ValueError('Nonmonotonic measured timestamps/attempts')
    expected=[attempts[0]!=0]+[b!=a+1 or not 19800<=d<=20200 or int(j)!=int(i)+1
        for a,b,d,i,j in zip(attempts,attempts[1:],deltas,index,index[1:])]
    if any(e and not g for e,g in zip(expected,gap)):
        raise ValueError('Unreported acquisition/timing gap in measured CSV')
    # Subtract Python integers BEFORE floating conversion (keeps low tick bits).
    elapsed=np.array([(t-ticks[0])/hz for t in ticks],dtype=float)
    uniform=all(d==20000 for d in deltas)
    event_times=[];origin=None
    sidecar=Path(path).parent/'recording_metadata.json'
    event_file=Path(path).parent/'events.json'
    if event_file.exists():
        if not sidecar.exists():raise ValueError('Events require matching recording metadata')
        meta=json.loads(sidecar.read_text(encoding='utf-8'))
        origin=meta.get('origin')
        if (meta.get('recording_id'),meta.get('time_domain_id')) != (rows[0]['SessionId'],rows[0]['TimeDomainId']):
            raise ValueError('Event metadata identity mismatch')
        events=json.loads(event_file.read_text(encoding='utf-8'))
        if len(events)!=meta['summary']['events_retained']:raise ValueError('Event sidecar count mismatch')
        for e in events:
            if e['validity_bits'] & 4 and not e['reason_bits'] & 32:
                event_times.append((int(e['current_ticks'])-ticks[0])/hz)
    return dict(t=elapsed,ticks=ticks,attempts=attempts,gap=np.array(gap,dtype=bool),
                uniform=uniform,clock_hz=hz,quality=quality,
                event_times=event_times,event_details_available=event_file.exists(),
                origin=origin,
                recording_id=rows[0]['SessionId'],time_domain_id=rows[0]['TimeDomainId'])


def break_plot(t, y, gap):
    """Insert separators before a discontinuity while retaining both real endpoints."""
    positions=np.flatnonzero(gap)[1:] if len(gap) and gap[0] else np.flatnonzero(gap)
    return np.insert(t,positions,np.nan),np.insert(np.asarray(y,dtype=float),positions,np.nan)
