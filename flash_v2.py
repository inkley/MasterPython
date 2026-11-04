"""Offline measured-v2 reference codec. No CAN, serial, MCU writes or erase actions.

This module is deliberately separate from the validated v1 CLI paths.
"""
import json
from pathlib import Path
import zlib

SCHEMA = json.loads(Path(__file__).with_name('metadata_v2_schema.json').read_text())
BLOCK = 1024
ERASED = b'\xff' * BLOCK
IMAGE_BYTES = 128 * BLOCK
SIZES = {1: ('sample', 1), 2: ('event', 1), 3: ('manifest', 2),
         4: ('journal', 2), 5: ('metadata', 1)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(value):
    value = getattr(value, 'bytes', value)
    require(isinstance(value, bytes) and len(value) == 16 and any(value), 'Invalid UUID')
    return value


def pack_fields(name, values):
    """Explicit offsets; reserved fields are generated, never caller-controlled."""
    layout = SCHEMA['layouts'][name]
    allowed = {f['name'] for f in layout['fields'] if not f['name'].startswith('reserved_zero')}
    require(set(values) == allowed, f'{name}: missing/extra fields')
    raw = bytearray(layout['bytes'])
    for f in layout['fields']:
        key, n, off = f['name'], f['bytes'], f['offset']
        if key.startswith('reserved_zero'):
            continue
        v = values[key]
        if key in ('magic', 'recording_id', 'time_domain_id', 'device_id', 'request_id', 'owned_page_bitmap'):
            require(isinstance(v, bytes) and len(v) == n, f'{key}: wrong byte length')
            raw[off:off+n] = v
        else:
            require(type(v) is int and 0 <= v < 1 << (8*n), f'{key}: unsigned range')
            raw[off:off+n] = v.to_bytes(n, 'little')
    return bytes(raw)


def unpack_fields(name, raw):
    layout = SCHEMA['layouts'][name]
    require(len(raw) == layout['bytes'], f'{name}: wrong size')
    values = {}
    for f in layout['fields']:
        key, n, off = f['name'], f['bytes'], f['offset']
        v = raw[off:off+n]
        if key.startswith('reserved_zero'):
            require(not any(v), f'{name}: reserved bytes')
        elif key in ('magic', 'recording_id', 'time_domain_id', 'device_id', 'request_id', 'owned_page_bitmap'):
            values[key] = v
        else:
            values[key] = int.from_bytes(v, 'little')
    return values


def empty_fields(name):
    """Construction aid only: semantic validation still required before acceptance."""
    result = {}
    for f in SCHEMA['layouts'][name]['fields']:
        key = f['name']
        if key.startswith('reserved_zero'):
            continue
        result[key] = bytes(f['bytes']) if key in (
            'magic', 'recording_id', 'time_domain_id', 'device_id', 'request_id', 'owned_page_bitmap') else 0
    return result


def seal(body):
    require(len(body) == 1016, 'Wrong CRC body size')
    return body + zlib.crc32(body).to_bytes(4, 'little') + b'CMIT'


def encode_block(kind, recording_id, domain_id, sequence, records, flags=17,
                 first_sample=0, first_tick=0):
    require(kind in SIZES, 'Unknown kind')
    name, payload_schema = SIZES[kind]
    if kind==5 and records and records[0].get("schema")==2: payload_schema=2
    h = dict(magic=b'IPLG', version=2, kind=kind,
             recording_id=identity(recording_id), time_domain_id=identity(domain_id),
             sequence=sequence, record_count=len(records), record_bytes=SCHEMA['layouts'][name]['bytes'],
             first_sample_index=first_sample, first_trigger_ticks=first_tick,
             nominal_tick_hz=20000000, nominal_period_us=1000, flags=flags,
             header_bytes=96, payload_schema=payload_schema)
    payload = b''.join(pack_fields(name, r) for r in records)
    require(len(payload) <= 920, 'Payload overflow')
    block = seal(pack_fields('header', h) + payload + b'\xff'*(920-len(payload)))
    decode_block(block)
    return block


def decode_block(raw):
    require(isinstance(raw, bytes) and len(raw) == BLOCK, 'Wrong block size')
    require(raw[1020:] == b'CMIT', 'Missing commit marker')
    require(int.from_bytes(raw[1016:1020], 'little') == zlib.crc32(raw[:1016]), 'Block CRC mismatch')
    h = unpack_fields('header', raw[:96])
    require(h['magic'] == b'IPLG' and h['version'] == 2 and h['header_bytes'] == 96, 'Unsupported envelope')
    identity(h['recording_id']); identity(h['time_domain_id'])
    require(h['kind'] in SIZES, 'Unknown kind')
    name, version = SIZES[h['kind']]
    size = SCHEMA['layouts'][name]['bytes']
    allowed_schema=(version,2) if h['kind']==5 else (version,)
    require(h['record_bytes'] == size and h['payload_schema'] in allowed_schema, 'Payload schema/size mismatch')
    require(h['nominal_tick_hz'] == 20000000 and h['nominal_period_us'] == 1000, 'Unsupported clock profile')
    require(h['flags'] & 17 == 17 and not h['flags'] & ~63, 'Invalid header flags')
    n = h['record_count']
    require(1 <= n <= 920//size and (h['kind'] in (1, 2) or n == 1), 'Invalid record count')
    if h['kind'] != 1:
        require(h['first_sample_index'] == h['first_trigger_ticks'] == 0, 'Non-data time/index')
    end = 96+n*size
    require(raw[end:1016] == b'\xff'*(1016-end), 'Invalid erased padding')
    records = [unpack_fields(name, raw[96+i*size:96+(i+1)*size]) for i in range(n)]
    if h['kind'] == 1:
        for r in records:
            require(r['p1'] <= 4095 and r['p2'] <= 4095, 'ADC range')
        require(h['first_trigger_ticks'] == records[0]['trigger_ticks'], 'First tick mismatch')
        for a, b in zip(records, records[1:]):
            require(a['trigger_ticks'] < b['trigger_ticks'] and a['attempt_index'] < b['attempt_index'], 'Nonmonotonic samples')
    return h, records


def footprint(data_count, event_count):
    require(type(data_count) is int and 1 <= data_count <= 18 and type(event_count) is int and 0 <= event_count <= 3, 'Invalid footprint')
    return {2, 3, *range(4, 4+event_count), *range(9, 9+data_count)}


def bitmap(pages):
    require(all(type(p) is int and 0 <= p < 128 for p in pages), 'Bitmap range')
    return sum(1 << p for p in pages).to_bytes(16, 'little')


def validate_metadata(m):
    require(m['schema'] in (1,2) and m['payload_bytes'] == 256, 'Metadata version')
    require(m['device_id_known'] in (0, 1) and bool(any(m['device_id'])) == bool(m['device_id_known']), 'Device identity validity')
    v = m['validity_bits']
    require(not v & ~63 and v & 6 == 6 and bool(v & 1) == bool(m['device_id_known']), 'Metadata validity bits')
    require(m['timestamp_reference'] == 1 and m['timer_width'] == 64 and m['timer_behavior_bits'] == 15, 'Timer/reference profile')
    require((m['tick_hz_numerator'], m['tick_hz_denominator'], m['nominal_period_ns'],
             m['nominal_tick_resolution_ns'], m['nominal_pair_hz']) == (20000000, 1, 1000000, 50, 1000), 'Clock metadata')
    require(m['capture_accepted_ticks'] <= m['first_attempt_ticks'] == m['schedule_origin_ticks'], 'Metadata origin')
    require(1 <= m['sample_limit'] <= 1024 and m['event_limit'] == 32, 'Capture limits')
    require(m['utc_schema'] == m['mapping_count'] == 0, 'Unsupported UTC/features')
    require((m['schema'],m['feature_bits']) in ((1,0),(2,1),(2,2),(2,3),(2,4)), 'Unsupported metadata feature profile')
    for bit, key in ((8, 'proxy_latency_bound_ns'), (16, 'drift_bound_ppb')):
        require(bool(v & bit) or m[key] == 0, 'Unknown bound must encode zero')
    require(not v & 32, 'Calibrated frequency unsupported in first profile')


def validate_events(events, summary, samples):
    reason_or = 0
    failed = set()
    for seq, e in enumerate(events):
        v, reason = e['validity_bits'], e['reason_bits']
        require(e['event_sequence'] == seq and reason and not reason & ~4095, 'Event sequence/reasons')
        require(not v & ~63 and v & 48 != 48 and e['detail_code'] == 0, 'Event validity/detail')
        for bit, key in ((1,'attempt_index'),(2,'previous_ticks'),(4,'current_ticks'),(8,'related_sample_index')):
            require(bool(v & bit) or e[key] == 0, 'Unknown event field')
        require(bool(v & 48) or e['missing_pair_count'] == 0, 'Unknown missing count')
        if v & 1:
            require(e['attempt_index'] < summary['attempts'], 'Event attempt range')
        if v & 8:
            require(e['related_sample_index'] < len(samples), 'Event sample range')
        if v & 6 == 6 and summary['validity_bits'] & 1:
            require(e['previous_ticks'] <= e['current_ticks'], 'Event time order')
        if reason & 2048:
            require(v & 6 == 6 and e['previous_ticks'] < e['current_ticks'], 'Planned pause needs known boundaries')
        if reason & 3:
            require(v & 5 == 5 and reason & 3 != 3 and e['attempt_index'] not in failed, 'Ambiguous/duplicate failed attempt')
            require(e['attempt_index'] == summary['attempts']-1, 'ADC fault must be terminal in bounded profile')
            failed.add(e['attempt_index'])
        reason_or |= reason
    require(not reason_or & ~summary['event_reason_or'], 'Manifest omits event reasons')
    valid_indices = {s['attempt_index'] for s in samples}
    require(not valid_indices & failed, 'Attempt both failed and valid')
    if not summary['events_lost']:
        timeouts = sum(bool(e['reason_bits'] & 1) for e in events)
        errors = sum(bool(e['reason_bits'] & 2) for e in events)
        require((timeouts, errors) == (summary['adc_timeouts'], summary['adc_errors']), 'Failure event accounting')
        require(valid_indices | failed == set(range(summary['attempts'])), 'Unexplained issued attempts')
        require(reason_or == summary['event_reason_or'], 'Reason aggregate mismatch')
        require(bool(summary['quality_bits'] & 32)==bool(reason_or & 32), 'Clock discontinuity quality')
        times = {s['attempt_index']:s['trigger_ticks'] for s in samples}
        times.update({e['attempt_index']:e['current_ticks'] for e in events if e['reason_bits'] & 3})
        require((times[0], times[summary['attempts']-1]) ==
                (summary['first_attempt_ticks'],summary['last_attempt_ticks']), 'Attempt endpoint timestamps')
        ordered = [times[i] for i in range(summary['attempts'])]
        require(not summary['validity_bits'] & 1 or all(a < b for a,b in zip(ordered,ordered[1:])), 'Attempt timestamp order')
        interval_bad=any(not 19800 <= b-a <= 20200 for a,b in zip(ordered,ordered[1:]))
        if summary['validity_bits'] & 1:
            require(bool(summary['quality_bits'] & 2)==interval_bad, 'Unreported/invented interval violation')
        require(bool(summary['quality_bits'] & 8)==any(e['validity_bits'] & 32 for e in events), 'Estimate provenance')
        if summary['validity_bits'] & 8:
            # Attempt index alone cannot locate schedule slots after unserviced gaps.
            require(not summary['quality_bits'] & 8 and not reason_or & 16,
                    'Phase assessment ambiguous across unserviced slots')
            phase_bad=any(abs(t-ordered[0]-i*20000)>200 for i,t in enumerate(ordered))
            require(bool(summary['quality_bits'] & 4)==phase_bad, 'Phase assessment mismatch')


def decode_recording(image):
    """Validate a complete v2 recording; extras/journals are handled by recovery."""
    require(isinstance(image, bytes) and len(image) == IMAGE_BYTES, 'Wrong partition size')
    page = lambda n: image[n*BLOCK:(n+1)*BLOCK]
    mh, rr = decode_block(page(2)); require(mh['kind'] == 3, 'Missing manifest')
    m = rr[0]
    require(m['schema'] == 2 and m['payload_bytes'] == 256, 'Manifest schema')
    n, d, e = m['samples'], m['data_blocks'], m['event_blocks']
    require(1 <= n <= 1024 and d == (n+56)//57 and 0 <= m['events_retained'] <= 32, 'Manifest sample/event limits')
    require(e == (m['events_retained']+13)//14 and m['metadata_blocks'] == 1, 'Manifest page counts')
    require(m['attempts'] == n+m['adc_timeouts']+m['adc_errors'] and m['attempts'] <= 0x100000000, 'Attempt accounting/range')
    # Bounded stop-on-ADC-fault profile cannot issue unbounded failed attempts.
    require(m['adc_timeouts']+m['adc_errors'] <= 1, 'ADC fault must stop capture')
    require(m['events_total'] == m['events_retained']+m['events_lost'] and m['events_lost'] <= 1, 'Event accounting')
    require(not m['events_lost'] or m['events_retained'] == 32, 'Overflow before event capacity')
    require(m['counter_rule'] == 1 and 1 <= m['stop_reason'] <= 6, 'Stop/counter rule')
    require(not m['quality_bits'] & ~255 and not m['validity_bits'] & ~31 and not m['event_reason_or'] & ~4095, 'Manifest flags')
    require(not m['validity_bits'] & 16, 'Aperture calibration unsupported')
    require(m['ram_rejected'] == m['unpaired_tail'] == m['tx_drops'] == m['tx_failures'] == 0, 'Unsupported bounded-loss profile')
    require(mh['sequence'] == 1+d+e, 'Manifest sequence')
    samples, events, metadata = [], [], None
    order = [3, *range(9,9+d), *range(4,4+e)]
    crc = 0
    for seq, p in enumerate(order):
        h, records = decode_block(page(p))
        expected_kind = 5 if p == 3 else 1 if p >= 9 else 2
        require(h['kind'] == expected_kind and h['sequence'] == seq, 'Page kind/sequence')
        require(all(h[k] == mh[k] for k in ('recording_id','time_domain_id','flags')), 'Mixed identity/domain/flags')
        if expected_kind == 5:
            metadata = records[0]; validate_metadata(metadata)
            require(h['payload_schema']==metadata['schema'], 'Metadata envelope/schema mismatch')
        elif expected_kind == 1:
            require(h['first_sample_index'] == len(samples) and len(records) == min(57,n-len(samples)), 'Data packing/index')
            samples.extend(records)
        else:
            require(len(records) == min(14,m['events_retained']-len(events)), 'Event packing')
            events.extend(records)
        crc = zlib.crc32(page(p), crc)
    require(crc == m['stream_crc32'] and len(samples) == n, 'Stream CRC/count')
    require(n <= metadata['sample_limit'], 'Capture exceeds declared limit')
    require(all(s['attempt_index']==i for i,s in enumerate(samples)), 'Bounded profile cannot resume after failed attempt')
    require(m['stop_reason'] != 2 or n == metadata['sample_limit'], 'Limit stop before limit')
    require(not (m['adc_timeouts']+m['adc_errors']) or n < metadata['sample_limit'], 'ADC fault after automatic stop')
    for a, b in zip(samples, samples[1:]):
        require(a['trigger_ticks'] < b['trigger_ticks'] and a['attempt_index'] < b['attempt_index'], 'Cross-block sample order')
    require(samples[-1]['attempt_index'] < m['attempts'], 'Sample attempt out of range')
    require((m['first_valid_ticks'],m['last_valid_ticks']) == (samples[0]['trigger_ticks'],samples[-1]['trigger_ticks']), 'Manifest sample times')
    require(m['first_attempt_ticks'] == metadata['first_attempt_ticks'] and m['capture_accepted_ticks'] == metadata['capture_accepted_ticks'], 'Metadata/manifest time mismatch')
    if m['validity_bits'] & 1:
        require(m['first_attempt_ticks'] <= m['first_valid_ticks'] <= m['last_valid_ticks'] <= m['last_attempt_ticks'], 'Attempt time bounds')
    if m['validity_bits'] & 2:
        require(m['capture_stop_ticks'] >= m['last_attempt_ticks'], 'Stop time before attempt')
    else:
        require(m['capture_stop_ticks'] == 0, 'Unknown stop time')
    if not m['validity_bits'] & 4:
        require(m['estimated_missing_slots'] == 0, 'Unknown missing total')
    validate_events(events, m, samples)
    quality, flags = m['quality_bits'], mh['flags']
    require(bool(quality & 1) == bool(m['adc_timeouts']+m['adc_errors']), 'ADC quality')
    require(bool(quality & 16) == bool(m['events_lost']), 'Event-loss quality')
    require(bool(quality & 32) == (not bool(m['validity_bits'] & 1)), 'Clock quality')
    require(bool(flags & 2) == bool(events) and bool(flags & 4) == bool(quality), 'Header quality/events')
    require(bool(flags & 8) == bool(m['events_lost']) and bool(flags & 32) == bool(quality & 8), 'Header loss flags')
    require(not quality & 4 or m['validity_bits'] & 8, 'Unassessed phase violation')
    require(not quality & (64|128), 'Loss flags unsupported in bounded profile')
    require(not m['estimated_missing_slots'] or (m['validity_bits'] & 4 and quality & 8), 'Missing estimate quality')
    if not m['events_lost']:
        reasons=m['event_reason_or']
        require(bool(quality & 2) == bool(reasons & (4|8)) or bool(quality & 4), 'Timing reason/quality')
        require(not quality & 8 or reasons & 16, 'Estimate without event')
    require(not m['events_lost'] or m['stop_reason'] in (4,5), 'Overflow stop reason')
    require(not m['events_lost'] or m['event_reason_or'] & 1024, 'Missing overflow reason')
    require(not (m['adc_timeouts']+m['adc_errors']) or m['stop_reason'] in (3,4,5), 'ADC stop reason')
    return dict(header=mh, metadata=metadata, summary=m, samples=samples,
                events=events, pages=footprint(d,e), manifest_crc=int.from_bytes(page(2)[1016:1020],'little'))


def encode_recording(recording_id, domain_id, samples, events, metadata, summary):
    """Caller supplies measured observations/summary; never synthesize UTC or gaps."""
    require(1 <= len(samples) <= 1024 and len(events) <= 32, 'Capture capacity')
    m = dict(summary)
    require(m['samples'] == len(samples) and m['events_retained'] == len(events), 'Caller count mismatch')
    quality = m['quality_bits']
    flags = 17 | (2 if events else 0) | (4 if quality else 0) | (8 if m['events_lost'] else 0) | (32 if quality & 8 else 0)
    blocks = [(3, encode_block(5,recording_id,domain_id,0,[metadata],flags))]
    for i in range(0,len(samples),57):
        records=samples[i:i+57]
        blocks.append((9+i//57,encode_block(1,recording_id,domain_id,len(blocks),records,flags,i,records[0]['trigger_ticks'])))
    for i in range(0,len(events),14):
        blocks.append((4+i//14,encode_block(2,recording_id,domain_id,len(blocks),events[i:i+14],flags)))
    crc=0
    for _, b in blocks:
        crc=zlib.crc32(b,crc)
    m['stream_crc32']=crc
    manifest=encode_block(3,recording_id,domain_id,len(blocks),[m],flags)
    image=bytearray(b'\xff'*IMAGE_BYTES)
    for p,b in blocks+[(2,manifest)]:
        image[p*BLOCK:(p+1)*BLOCK]=b
    result=bytes(image)
    decode_recording(result)
    return result


def decode_journal(raw):
    h, rows=decode_block(raw);j=rows[0]
    require(h['kind']==4 and j['schema']==2 and not j['flags_zero'], 'Journal schema')
    require(j['recording_id']==h['recording_id'] and j['operation'] in (1,2), 'Journal target/operation')
    identity(j['request_id'])
    require(j['generation']>0 and h['sequence']==j['generation'] & 0xffffffff, 'Journal generation')
    require(1<=j['samples']<=1024 and j['data_blocks']==(j['samples']+56)//57 and j['metadata_blocks']==1, 'Journal counts')
    require(j['owned_page_bitmap']==bitmap(footprint(j['data_blocks'],j['event_blocks'])), 'Journal footprint')
    return h,j


def encode_journal(record, operation, generation, request_id):
    h,m=record['header'],record['summary']
    j=dict(recording_id=h['recording_id'],manifest_crc32=record['manifest_crc'],
           operation=operation,flags_zero=0,generation=generation,request_id=identity(request_id),
           data_blocks=m['data_blocks'],samples=m['samples'],metadata_blocks=1,
           event_blocks=m['event_blocks'],owned_page_bitmap=bitmap(record['pages']),schema=2)
    result=encode_block(4,h['recording_id'],h['time_domain_id'],generation & 0xffffffff,[j],h['flags'])
    decode_journal(result)
    return result


def recover_image(image):
    """Read-only classification; no salvage promoted to complete, no erase plan."""
    require(isinstance(image,bytes) and len(image)==IMAGE_BYTES,'Wrong partition size')
    pages=[image[p*BLOCK:(p+1)*BLOCK] for p in range(128)]
    nonblank={p for p,b in enumerate(pages) if b!=ERASED}
    if not nonblank:
        return dict(state='EMPTY',samples=0,quarantine=[])
    if pages[2][:6]==b'IPLG\x01\0':
        from flash_lifecycle import lifecycle_view
        return dict(state='LEGACY_V1_PROTECTED',legacy=lifecycle_view(image),quarantine=sorted(nonblank))
    valid=[];invalid=[]
    for p in (0,1):
        if pages[p]==ERASED:
            continue
        try:
            h,j=decode_journal(pages[p]);valid.append((p,h,j))
        except ValueError:
            invalid.append(p)
    valid.sort(key=lambda item:item[2]['generation'])
    uncertain=bool(invalid and not valid)
    if len(valid)==2 and valid[0][2]['generation']==valid[1][2]['generation'] and pages[0]!=pages[1]:
        uncertain=True
    latest=valid[-1] if valid and not uncertain else None
    try:
        record=decode_recording(image)
    except ValueError as exc:
        state='JOURNAL_UNCERTAIN' if uncertain else 'INCOMPLETE_DAMAGED_OR_UNSUPPORTED'
        if latest and latest[2]['operation']==2:
            owned=footprint(latest[2]['data_blocks'],latest[2]['event_blocks'])
            if not (nonblank-{0,1}):
                state='CLEARED'
            elif not (nonblank-{0,1}-owned):
                # Even the owned region may contain a newer torn write. No erase authority.
                state='CLEAR_PENDING_PROTECTED'
        return dict(state=state,samples=0,quarantine=sorted(nonblank),reason=str(exc))
    h,m=record['header'],record['summary']
    if record['metadata']['schema']==2:
        return dict(state='BENCH_RAM_IMAGE_PROTECTED',samples=len(record['samples']),quarantine=sorted(nonblank),recording=record)
    extras=(nonblank-record['pages']-{p for p,_,_ in valid}) | set(invalid)
    state='JOURNAL_UNCERTAIN' if uncertain else 'COMMITTED'
    if latest and latest[1]['recording_id']==h['recording_id']:
        j=latest[2]
        match=(latest[1]['time_domain_id']==h['time_domain_id'] and latest[1]['flags']==h['flags']
               and j['manifest_crc32']==record['manifest_crc'] and j['samples']==m['samples']
               and j['owned_page_bitmap']==bitmap(record['pages']))
        if not match:
            state='JOURNAL_UNCERTAIN'
        else:
            state='ACKNOWLEDGED' if j['operation']==1 else 'CLEAR_PENDING'
    if extras and state!='JOURNAL_UNCERTAIN':
        state+='_WITH_QUARANTINE'
    return dict(state=state,samples=len(record['samples']),quarantine=sorted(extras),recording=record)
