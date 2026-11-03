"""Offline reference-codec tests; no MCU access or physical power-failure claim."""
import json
from pathlib import Path
import unittest
import uuid
import zlib
import flash_v2 as v

RID=uuid.UUID('12345678-1234-4234-8234-123456789abc')
DOMAIN=uuid.UUID('aabbccdd-1234-4234-8234-123456789abc')
REQUEST=uuid.UUID('fedcba98-1234-4234-8234-123456789abc')


def fixture(n=58, event_count=0, lost=0, timeout=False, start=100000):
    samples=[dict(trigger_ticks=start+i*20000,attempt_index=i,p1=i%4096,p2=(i+17)%4096) for i in range(n)]
    events=[]
    for i in range(event_count):
        e=v.empty_fields('event')
        e.update(event_sequence=i,reason_bits=2048,previous_ticks=start-1,
                 current_ticks=start,validity_bits=6)  # explicit boundaries, no invented missing slots
        events.append(e)
    meta=v.empty_fields('metadata')
    meta.update(schema=1,payload_bytes=256,timestamp_reference=1,
                tick_hz_numerator=20000000,tick_hz_denominator=1,nominal_period_ns=1000000,
                timer_width=64,timer_behavior_bits=15,schedule_origin_ticks=start,
                first_attempt_ticks=start,capture_accepted_ticks=start-1,
                nominal_tick_resolution_ns=50,validity_bits=6,sample_limit=n,event_limit=32,nominal_pair_hz=1000)
    m=v.empty_fields('manifest')
    m.update(schema=2,payload_bytes=256,samples=n,attempts=n,events_retained=len(events),
             events_total=len(events)+lost,events_lost=lost,first_valid_ticks=start,
             last_valid_ticks=samples[-1]['trigger_ticks'],capture_stop_ticks=samples[-1]['trigger_ticks']+500,
             first_attempt_ticks=start,last_attempt_ticks=samples[-1]['trigger_ticks'],capture_accepted_ticks=start-1,
             data_blocks=(n+56)//57,event_blocks=(event_count+13)//14,metadata_blocks=1,
             stop_reason=2,counter_rule=1,validity_bits=7,event_reason_or=2048 if events else 0)
    if lost:
        m.update(quality_bits=16,stop_reason=4,event_reason_or=m['event_reason_or']|1024)
    if timeout:
        meta['sample_limit']=n+1
        e=v.empty_fields('event');e.update(event_sequence=len(events),attempt_index=n,
            current_ticks=start+n*20000,reason_bits=1,validity_bits=5)
        events.append(e)
        m.update(attempts=n+1,adc_timeouts=1,events_retained=len(events),events_total=len(events),
                 event_blocks=(len(events)+13)//14,quality_bits=1,stop_reason=3,
                 last_attempt_ticks=e['current_ticks'],capture_stop_ticks=e['current_ticks']+500,
                 event_reason_or=m['event_reason_or']|1)
    return samples,events,meta,m


def image(**kwargs):
    return v.encode_recording(RID,DOMAIN,*fixture(**kwargs))


def replace_page(raw,p,block):
    result=bytearray(raw);result[p*1024:(p+1)*1024]=block;return bytes(result)


def journal_image(raw,op=1,generation=1,p=0):
    r=v.decode_recording(raw)
    return replace_page(raw,p,v.encode_journal(r,op,generation,REQUEST))


def mutate(raw, offset, value):
    body=bytearray(raw[:1016]);body[offset:offset+len(value)]=value
    return v.seal(bytes(body))


class V2Tests(unittest.TestCase):
    def test_schema_layout_and_frozen_v1_separation(self):
        self.assertEqual(v.SCHEMA['version'],2)
        self.assertEqual(v.SCHEMA['layouts']['sample']['bytes'],16)
        golden=v.pack_fields('sample',dict(trigger_ticks=0x100000002,attempt_index=17,p1=0xabc,p2=0xdef))
        self.assertEqual(golden,bytes.fromhex('020000000100000011000000bc0aef0d'))
        self.assertEqual(v.bitmap({2,3,9}),bytes.fromhex('0c02')+bytes(14))
        self.assertEqual(zlib.crc32(b'123456789'),0xcbf43926)
        from test_flash_recovery import fixture as old_fixture
        old=old_fixture()
        with self.assertRaises(ValueError):v.decode_recording(old)
        self.assertEqual(v.recover_image(old)['state'],'LEGACY_V1_PROTECTED')

    def test_roundtrip_sample_boundaries(self):
        for n in (1,57,58,1023,1024):
            raw=image(n=n);r=v.decode_recording(raw)
            self.assertEqual(r['samples'],fixture(n=n)[0])
            self.assertEqual(r['summary']['samples'],n)
            self.assertEqual(r['header']['time_domain_id'],DOMAIN.bytes)
            self.assertEqual(v.recover_image(raw)['state'],'COMMITTED')

    def test_event_boundaries_and_overflow(self):
        for n in (0,14,15,28,29,32):
            raw=image(event_count=n);r=v.decode_recording(raw)
            self.assertEqual(len(r['events']),n)
            self.assertEqual(r['summary']['event_blocks'],(n+13)//14)
        r=v.decode_recording(image(event_count=32,lost=1))
        self.assertEqual(r['summary']['events_total'],33)
        with self.assertRaises(ValueError):image(event_count=31,lost=1)
        with self.assertRaises(ValueError):image(event_count=32,lost=2)
        with self.assertRaises(ValueError):image(event_count=33)

    def test_failed_attempt_retained_and_unknown_utc(self):
        r=v.decode_recording(image(timeout=True))
        self.assertEqual(r['summary']['attempts'],59)
        self.assertEqual(r['summary']['adc_timeouts'],1)
        self.assertEqual(r['metadata']['mapping_count'],0)
        self.assertEqual(r['metadata']['validity_bits'] & 24,0)
        s,e,meta,m=fixture(timeout=True)
        # Internally coherent general trace, but invalid for stop-on-first-fault:
        # valid samples continued after failed issued attempt10.
        for pair in s[10:]:
            pair['attempt_index']+=1
            pair['trigger_ticks']+=20000
        e[-1].update(attempt_index=10,current_ticks=s[0]['trigger_ticks']+10*20000)
        m.update(last_valid_ticks=s[-1]['trigger_ticks'],last_attempt_ticks=s[-1]['trigger_ticks'])
        with self.assertRaisesRegex(ValueError,'cannot resume|terminal'):
            v.encode_recording(RID,DOMAIN,s,e,meta,m)

    def test_uint64_times_across_low_word_rollover(self):
        r=v.decode_recording(image(start=2**32-10000))
        self.assertGreater(r['samples'][-1]['trigger_ticks'],2**32)
        with self.assertRaises(ValueError):image(start=2**64-100)

    def test_actual_irregular_interval_and_estimated_gap(self):
        for delta,missing in ((20500,0),(40000,1)):
            s,e,meta,m=fixture(n=2)
            s[1]['trigger_ticks']=s[0]['trigger_ticks']+delta
            event=v.empty_fields('event')
            event.update(event_sequence=0,attempt_index=1,previous_ticks=s[0]['trigger_ticks'],
                current_ticks=s[1]['trigger_ticks'],related_sample_index=1,reason_bits=8,
                validity_bits=15)
            if missing:
                event.update(reason_bits=24,validity_bits=47,missing_pair_count=missing)
            e=[event]
            m.update(last_valid_ticks=s[1]['trigger_ticks'],last_attempt_ticks=s[1]['trigger_ticks'],
                capture_stop_ticks=s[1]['trigger_ticks']+500,events_retained=1,events_total=1,
                event_blocks=1,event_reason_or=event['reason_bits'],quality_bits=2|(8 if missing else 0),
                estimated_missing_slots=missing)
            raw=v.encode_recording(RID,DOMAIN,s,e,meta,m)
            r=v.decode_recording(raw)
            self.assertEqual(r['samples'][1]['trigger_ticks']-r['samples'][0]['trigger_ticks'],delta)
            self.assertEqual(r['summary']['attempts'],2)
            self.assertEqual(r['summary']['estimated_missing_slots'],missing)

    def test_silent_jitter_and_phase_claim_rejected(self):
        s,e,meta,m=fixture(n=2)
        s[1]['trigger_ticks']+=500
        m.update(last_valid_ticks=s[1]['trigger_ticks'],last_attempt_ticks=s[1]['trigger_ticks'],
                 capture_stop_ticks=s[1]['trigger_ticks']+500)
        with self.assertRaisesRegex(ValueError,'interval violation'):
            v.encode_recording(RID,DOMAIN,s,e,meta,m)
        s,e,meta,m=fixture(n=4)
        m['validity_bits']|=8
        v.encode_recording(RID,DOMAIN,s,e,meta,m)  # consistent assessed phase
        m['quality_bits']=4
        with self.assertRaisesRegex(ValueError,'Phase assessment'):
            v.encode_recording(RID,DOMAIN,s,e,meta,m)

    def test_empty_oversize_and_input_ranges(self):
        for n in (0,1025):
            s,e,meta,m=fixture(n=max(1,n))
            if n==0:s=[]
            with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)
        for key,value in [('p1',4096),('p2',-1),('attempt_index',2**32),('trigger_ticks',2**64)]:
            s,e,meta,m=fixture();s[0][key]=value
            with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)

    def test_every_byte_corruption_in_all_kinds(self):
        raw=image(event_count=1)
        raw=journal_image(raw)
        for p in (0,2,3,4,9):
            block=raw[p*1024:(p+1)*1024]
            for offset in range(1024):
                b=bytearray(block);b[offset]^=1
                with self.assertRaises(ValueError):v.decode_block(bytes(b))

    def test_rechecksummed_header_and_padding_faults(self):
        raw=image();block=raw[9*1024:10*1024]
        changes=[(4,b'\x03\0'),(6,b'\x09\0'),(8,bytes(16)),(24,bytes(16)),
                 (44,b'\0\0'),(46,b'\x0c\0'),(72,b'\x80\0\0\0'),
                 (76,b'\x40\0'),(78,b'\x01\0'),(80,b'\x02\0\0\0'),(84,b'\x01')]
        for off,value in changes:
            with self.assertRaises(ValueError):v.decode_block(mutate(block,off,value))
        last=raw[10*1024:11*1024]
        with self.assertRaises(ValueError):v.decode_block(mutate(last,112,b'\0'))

    def test_no_complete_record_at_any_program_prefix(self):
        complete=image(n=58,event_count=1)
        order=[3,9,10,4,2]
        raw=b'\xff'*v.IMAGE_BYTES
        for p in order:
            block=complete[p*1024:(p+1)*1024]
            for cut in range(0,1024,4):
                torn=replace_page(raw,p,block[:cut]+b'\xff'*(1024-cut))
                state=v.recover_image(torn)
                self.assertEqual(state['samples'],0)
                self.assertNotIn(state['state'],('COMMITTED','ACKNOWLEDGED'))
            raw=replace_page(raw,p,block)
        self.assertEqual(raw,complete)
        self.assertEqual(v.recover_image(raw)['samples'],58)

    def test_missing_duplicate_foreign_and_mixed_version_pages(self):
        raw=image(n=58)
        for bad in (replace_page(raw,9,v.ERASED),replace_page(raw,10,raw[9*1024:10*1024])):
            self.assertEqual(v.recover_image(bad)['samples'],0)
        other=v.encode_recording(uuid.uuid4(),uuid.uuid4(),*fixture(n=58))
        self.assertEqual(v.recover_image(replace_page(raw,10,other[10*1024:11*1024]))['samples'],0)
        from test_flash_recovery import fixture as old_fixture
        old=old_fixture()
        self.assertEqual(v.recover_image(replace_page(raw,9,old[9*1024:10*1024]))['samples'],0)

    def test_rechecksummed_semantic_inputs(self):
        for key,value in [('validity_bits',64),('mapping_count',1),('utc_schema',1),
                          ('proxy_latency_bound_ns',100),('device_id_known',1),('sample_limit',1)]:
            s,e,meta,m=fixture();meta[key]=value
            with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)
        for key,value in [('attempts',100),('samples',1),('data_blocks',1),('events_lost',1),
                          ('first_valid_ticks',1),('capture_stop_ticks',1),('quality_bits',1),
                          ('validity_bits',31),('stop_reason',99),('estimated_missing_slots',5)]:
            s,e,meta,m=fixture();m[key]=value
            with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)

    def test_cross_block_order_and_event_semantics(self):
        s,e,meta,m=fixture();s[57]['trigger_ticks']=s[56]['trigger_ticks']
        with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)
        for key,value in [('event_sequence',1),('reason_bits',0),('validity_bits',48),
                          ('attempt_index',1),('current_ticks',1),('detail_code',1)]:
            s,e,meta,m=fixture(event_count=1);e[0][key]=value
            with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)

    def test_ack_delete_retention_and_foreign_quarantine(self):
        raw=image(n=1024,event_count=32)
        ack=journal_image(raw)
        self.assertEqual(v.recover_image(ack)['state'],'ACKNOWLEDGED')
        self.assertEqual(ack[2048:],raw[2048:])
        delete=journal_image(ack,op=2,generation=2,p=1)
        self.assertEqual(v.recover_image(delete)['state'],'CLEAR_PENDING')
        extra=replace_page(ack,7,b'\0'+v.ERASED[1:])
        self.assertEqual(v.recover_image(extra)['state'],'ACKNOWLEDGED_WITH_QUARANTINE')
        self.assertIn(7,v.recover_image(extra)['quarantine'])

    def test_torn_journal_and_generation_conflict(self):
        raw=image();ack=journal_image(raw);delete=journal_image(ack,op=2,generation=2,p=1)
        block=delete[1024:2048]
        for cut in range(0,1024,4):
            torn=replace_page(ack,1,block[:cut]+b'\xff'*(1024-cut))
            r=v.recover_image(torn)
            self.assertNotIn(r['state'],('CLEAR_PENDING','CLEARED'))
            self.assertEqual(r['samples'],58)
        conflict=journal_image(ack,op=2,generation=1,p=1)
        self.assertEqual(v.recover_image(conflict)['state'],'JOURNAL_UNCERTAIN')

    def test_interrupted_erase_prefixes_never_claim_intact_record(self):
        raw=image(n=1,event_count=1);raw=journal_image(raw)
        raw=journal_image(raw,op=2,generation=2,p=1)
        for p in (9,4,3,2):
            block=raw[p*1024:(p+1)*1024]
            for cut in range(4,1025,4):
                damaged=replace_page(raw,p,b'\xff'*cut+block[cut:])
                result=v.recover_image(damaged)
                self.assertEqual(result['samples'],0)
                self.assertNotIn(result['state'],('COMMITTED','ACKNOWLEDGED'))
            raw=replace_page(raw,p,v.ERASED)
        self.assertEqual(v.recover_image(raw)['state'],'CLEARED')

    def test_stale_journal_cannot_ack_new_record(self):
        old=image()
        new=v.encode_recording(uuid.uuid4(),uuid.uuid4(),*fixture())
        for op in (1,2):
            j=journal_image(old,op=op)[:1024]
            r=v.recover_image(replace_page(new,0,j))
            self.assertEqual(r['state'],'COMMITTED')
        # Old DELETE footprint overlaps a newer torn capture; never infer erase authority.
        old_delete=journal_image(old,op=2)[:1024]
        partial=replace_page(b'\xff'*v.IMAGE_BYTES,0,old_delete)
        partial=replace_page(partial,9,new[9*1024:9*1024+96]+b'\xff'*928)
        self.assertEqual(v.recover_image(partial)['state'],'CLEAR_PENDING_PROTECTED')

    def test_caller_observations_are_not_modified(self):
        import copy
        args=fixture(event_count=1)
        saved=copy.deepcopy(args)
        raw=v.encode_recording(RID,DOMAIN,*args)
        self.assertEqual(args,saved)
        before=bytes(raw)
        v.recover_image(raw)
        self.assertEqual(raw,before)

    def test_journal_bitmap_bounds_and_wrong_target(self):
        raw=journal_image(image());b=raw[:1024]
        # payload bitmap offset64; inject journal-page ownership and valid CRC.
        mask=bytearray(b[160:176]);mask[0]|=1
        with self.assertRaises(ValueError):v.decode_journal(mutate(b,160,bytes(mask)))
        other=mutate(b,24,uuid.uuid4().bytes)
        self.assertEqual(v.recover_image(replace_page(raw,0,other))['state'],'JOURNAL_UNCERTAIN')

    def test_truncated_partition_and_empty(self):
        self.assertEqual(v.recover_image(b'\xff'*v.IMAGE_BYTES)['state'],'EMPTY')
        for n in (0,1024,v.IMAGE_BYTES-1,v.IMAGE_BYTES+1):
            with self.assertRaises(ValueError):v.recover_image(b'\xff'*n)


if __name__=='__main__':unittest.main()
