"""Bench metadata/host guards; firmware execution still needs on-device testing."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import uuid
import numpy as np
import flash_v2 as v
from test_flash_v2 import fixture,RID,DOMAIN,image
from measured_export import export_v2
from measured_time import load_measured_time
from flash_lifecycle import verified_file
from InkleySensor import CANBusCommander


def bench_image():
    s,e,meta,m=fixture(n=64)
    for pair in s[16:]:pair['trigger_ticks']+=80000
    event=v.empty_fields('event')
    event.update(event_sequence=0,attempt_index=16,previous_ticks=s[15]['trigger_ticks'],
        current_ticks=s[16]['trigger_ticks'],missing_pair_count=4,related_sample_index=16,
        reason_bits=24,validity_bits=47)
    meta.update(schema=2,feature_bits=1)
    m.update(last_valid_ticks=s[-1]['trigger_ticks'],last_attempt_ticks=s[-1]['trigger_ticks'],
        capture_stop_ticks=s[-1]['trigger_ticks']+500,event_blocks=1,events_retained=1,events_total=1,
        event_reason_or=24,quality_bits=10,estimated_missing_slots=4)
    return v.encode_recording(RID,DOMAIN,s,[event],meta,m)


class BenchTests(unittest.TestCase):
    def test_bench_profile_is_explicit_and_not_committed_recovery(self):
        raw=bench_image();r=v.decode_recording(raw)
        self.assertEqual(r['metadata']['schema'],2)
        self.assertEqual(r['metadata']['feature_bits'],1)
        self.assertEqual(v.decode_block(raw[3072:4096])[0]['payload_schema'],2)
        self.assertEqual(v.recover_image(raw)['state'],'BENCH_RAM_IMAGE_PROTECTED')
        self.assertEqual(r['samples'][16]['trigger_ticks']-r['samples'][15]['trigger_ticks'],100000)

    def test_normal_profile_remains_unchanged(self):
        self.assertEqual(v.recover_image(image())['state'],'COMMITTED')
        s,e,meta,m=fixture();meta['feature_bits']=1
        with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)
        meta.update(schema=2,feature_bits=2)
        with self.assertRaises(ValueError):v.encode_recording(RID,DOMAIN,s,e,meta,m)

    def test_export_carries_bench_label_and_real_tick_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'bench';meta=export_v2(bench_image(),p,'MCU_RAM')
            self.assertEqual(meta['origin'],'MCU_BENCH_RAM')
            self.assertTrue(meta['bench_injection'])
            self.assertTrue(verified_file(p/'recording.bin')['bench_injection'])
            timing=load_measured_time(p/'samples.csv',np.arange(64))
            self.assertTrue(timing['gap'][16]);self.assertEqual(timing['origin'],'MCU_BENCH_RAM')

    def test_bench_cannot_be_exported_as_actual_flash(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'bad'
            with self.assertRaises(ValueError):export_v2(bench_image(),p,'MCU_FLASH')
            self.assertFalse(p.exists())

    def test_flash_ack_and_clear_reject_bench_before_any_command(self):
        cli=CANBusCommander();cli._flash_ready=Mock()
        evidence=dict(recording_id=RID,manifest_crc=1,count=64,format_version=2,bench_injection=True)
        with patch('InkleySensor.verified_file',return_value=evidence),contextlib.redirect_stdout(io.StringIO()):
            cli.do_ack_flash('bench.bin');cli.do_clear_flash('bench.bin')
        cli._flash_ready.assert_not_called()

    def test_normal_file_cannot_discard_bench_ram(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'normal.bin';p.write_bytes(image())
            cli=CANBusCommander();cli._bench_ready=Mock()
            with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_bench_discard(str(p))
            cli._bench_ready.assert_not_called()

    def test_old_firmware_starts_no_bench(self):
        cli=CANBusCommander();cli._measured_ready=Mock(return_value=True)
        cli._recv_u32_response=Mock(return_value=0x80000003)
        with contextlib.redirect_stdout(io.StringIO()):self.assertFalse(cli._bench_ready())
        cli._recv_u32_response.assert_called_once_with(0x30,value_u32=8)

    def test_bench_start_binds_saved_protected_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'normal.bin';p.write_bytes(image())
            info=verified_file(p)
            cli=CANBusCommander();cli._bench_ready=Mock(return_value=True)
            cli.do_measured_init=Mock(side_effect=lambda _:setattr(cli,'_measured_domain_id',DOMAIN))
            cli._bench_stage=Mock(return_value=True);cli._recv_u32_response=Mock(return_value=64)
            with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_bench_gap(str(p))
            self.assertEqual(cli._bench_stage.call_args.args[1],RID)
            cli._recv_u32_response.assert_called_once_with(0x39,value_u32=info['manifest_crc'])

    def test_discard_targets_exact_exported_bench_file(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'bench.bin';p.write_bytes(bench_image());info=verified_file(p)
            cli=CANBusCommander();cli._bench_ready=Mock(return_value=True)
            cli._bench_stage=Mock(return_value=True);cli._recv_u32_response=Mock(return_value=0)
            with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_bench_discard(str(p))
            self.assertEqual(cli._bench_stage.call_args.args[1],RID)
            cli._recv_u32_response.assert_called_once_with(0x3d,value_u32=info['manifest_crc'])

    def test_invalid_stack_response_not_reported_as_margin(self):
        cli=CANBusCommander();cli._bench_ready=Mock(return_value=True)
        cli._recv_u32_response=Mock(return_value=5000)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):cli.do_stack_status('')
        self.assertIn('Invalid stack',output.getvalue())
        self.assertNotIn('pattern-unused',output.getvalue())


if __name__=='__main__':unittest.main()
