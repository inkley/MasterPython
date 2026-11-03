"""Validated v2 downloads/exports, shared by RAM and persistent recordings."""
import csv
import json
from pathlib import Path
import uuid
from flash_v2 import decode_block, decode_recording


def download_v2(read_block, manifest=None):
    manifest = read_block(2) if manifest is None else manifest
    h, rows = decode_block(manifest)
    if h['kind'] != 3:
        raise ValueError('Expected measured manifest')
    m = rows[0]
    n, d, e = m['samples'], m['data_blocks'], m['event_blocks']
    if not 1 <= n <= 1024 or d != (n+56)//57 or not 0 <= e <= 3 or m['metadata_blocks'] != 1:
        raise ValueError('Untrusted measured block counts')
    image = bytearray(b'\xff'*131072)
    image[2048:3072] = manifest
    for p in [3, *range(9,9+d), *range(4,4+e)]:
        block = read_block(p)
        if len(block) != 1024:
            raise ValueError('Incomplete measured block')
        image[p*1024:(p+1)*1024] = block
    raw = bytes(image)
    decode_recording(raw)
    return raw


def export_v2(image, directory, origin):
    if origin not in ('MCU_RAM','MCU_FLASH','OFFLINE','MCU_BENCH_RAM'):
        raise ValueError('Unknown export origin')
    r = decode_recording(image)
    h, m = r['header'], r['summary']
    bench=r['metadata']['schema']==2
    if origin=='MCU_BENCH_RAM' and not bench:raise ValueError('Bench origin requires bench metadata')
    if bench:
        if origin=='MCU_FLASH':raise ValueError('Bench profile is RAM-only; unexpected persisted bench data')
        if origin!='OFFLINE':origin='MCU_BENCH_RAM'
    recording = str(uuid.UUID(bytes=h['recording_id']))
    domain = str(uuid.UUID(bytes=h['time_domain_id']))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory/'recording.bin').write_bytes(image)
    metadata = dict(format_version=2, origin=origin, recording_id=recording,
                    time_domain_id=domain, time_basis='RAW_TRIGGER_TICKS',
                    timestamp_reference='PRE_SOFTWARE_TRIGGER', utc=None,
                    utc_error_bound_ns=None, summary=m,
                    clock={k:(v.hex() if isinstance(v,bytes) else v) for k,v in r['metadata'].items()},
                    reconstructed_partition=True,bench_injection=bench)
    (directory/'recording_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    (directory/'events.json').write_text(json.dumps(r['events'],indent=2)+'\n',encoding='utf-8')
    with (directory/'samples.csv').open('x',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['Timestamp','SampleIndex','Pressure1','Pressure2','SessionId','TimeDomainId',
                         'AttemptIndex','TriggerTicks','TickHz','TimeBasis','GapBefore','QualityFlags'])
        prev=None
        related={e['related_sample_index'] for e in r['events'] if e['validity_bits'] & 8}
        for i,s in enumerate(r['samples']):
            gap=(s['attempt_index']!=0 if prev is None else
                 s['attempt_index']!=prev['attempt_index']+1 or not 19800<=s['trigger_ticks']-prev['trigger_ticks']<=20200)
            writer.writerow(['',i,s['p1'],s['p2'],recording,domain,s['attempt_index'],s['trigger_ticks'],
                             20000000,'RAW_TRIGGER_TICKS',int(gap or i in related),m['quality_bits']])
            prev=s
    return metadata
