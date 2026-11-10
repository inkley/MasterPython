"""Controlled bench provenance and host safety; not MCU execution evidence."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import flash_v2 as v
from .test_flash_v2 import fixture, RID, DOMAIN
from measured_export import export_v2
from InkleySensor import CANBusCommander


def fault_image(profile):
    if profile in (2,3):
        s,e,meta,m=fixture(n=15,timeout=True)
        meta.update(schema=2,feature_bits=profile,sample_limit=64)
        if profile==2:
            e[-1]['reason_bits']=2
            m.update(adc_timeouts=0,adc_errors=1,event_reason_or=2)
    else:
        s,e,meta,m=fixture(n=34)
        meta.update(schema=2,feature_bits=4,sample_limit=64)
        for i,p in enumerate(s):p['trigger_ticks']=100000+i*100000
        e=[]
        for i in range(1,33):
            ev=v.empty_fields('event')
            ev.update(event_sequence=i-1,attempt_index=i,previous_ticks=s[i-1]['trigger_ticks'],
                current_ticks=s[i]['trigger_ticks'],missing_pair_count=4,related_sample_index=i,
                reason_bits=24,validity_bits=47)
            e.append(ev)
        m.update(last_valid_ticks=s[-1]['trigger_ticks'],last_attempt_ticks=s[-1]['trigger_ticks'],
            capture_stop_ticks=s[-1]['trigger_ticks']+500,events_retained=32,events_total=33,
            events_lost=1,event_blocks=3,quality_bits=26,event_reason_or=1048,
            estimated_missing_slots=132,stop_reason=4)
    return v.encode_recording(RID,DOMAIN,s,e,meta,m)


class FaultBenchTests(unittest.TestCase):
    def test_fault_and_overflow_roundtrip(self):
        for profile in (2,3,4):
            raw=fault_image(profile);r=v.decode_recording(raw);m=r['summary']
            self.assertEqual(v.recover_image(raw)['state'],'BENCH_RAM_IMAGE_PROTECTED')
            if profile==4:
                self.assertEqual((m['events_retained'],m['events_total'],m['events_lost'],m['stop_reason']),(32,33,1,4))
            else:
                self.assertEqual((m['samples'],m['attempts'],m['stop_reason']),(15,16,3))
                self.assertEqual(r['events'][-1]['attempt_index'],15)
                self.assertFalse(r['events'][-1]['validity_bits']&8)

    def test_exports_identify_each_profile_and_reject_flash_origin(self):
        for profile,name in ((2,'adc_error'),(3,'adc_timeout'),(4,'event_overflow')):
            with tempfile.TemporaryDirectory() as temp:
                raw=fault_image(profile)
                result=export_v2(raw,Path(temp)/'ram','MCU_RAM')
                self.assertEqual(result['bench_profile'],name)
                self.assertEqual(result['origin'],'MCU_BENCH_RAM')
                with self.assertRaises(ValueError):export_v2(raw,Path(temp)/'flash','MCU_FLASH')

    def test_each_command_binds_protected_identity(self):
        for name,command in (('adc_error',0x3a),('adc_timeout',0x3b),('event_overflow',0x3c)):
            cli=CANBusCommander();cli._bench_ready=Mock(return_value=True)
            cli.do_measured_init=Mock(side_effect=lambda _:setattr(cli,'_measured_domain_id',DOMAIN))
            cli._bench_stage=Mock(return_value=True)
            cli._recv_u32_response=Mock(side_effect=[0x424e4302,64])
            evidence=dict(format_version=2,bench_injection=False,recording_id=RID,manifest_crc=123)
            with patch('InkleySensor.verified_file',return_value=evidence),contextlib.redirect_stdout(io.StringIO()):
                cli.do_measured_bench_fault(name+' "protected file.bin"')
            self.assertEqual(cli._bench_stage.call_args.args[1],RID)
            self.assertEqual(cli._recv_u32_response.call_args.args,(command,))
            self.assertEqual(cli._recv_u32_response.call_args.kwargs,dict(value_u32=123))

    def test_old_capability_does_not_stage_or_start(self):
        cli=CANBusCommander();cli._bench_ready=Mock(return_value=True)
        cli._recv_u32_response=Mock(return_value=0x80000003);cli._bench_stage=Mock()
        evidence=dict(format_version=2,bench_injection=False)
        with patch('InkleySensor.verified_file',return_value=evidence),contextlib.redirect_stdout(io.StringIO()):
            cli.do_measured_bench_fault('adc_error protected.bin')
        cli._bench_stage.assert_not_called()
        cli._recv_u32_response.assert_called_once_with(0x30,value_u32=9)

    def test_bad_input_and_bench_backup_start_no_commands(self):
        cli=CANBusCommander();cli._bench_ready=Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.do_measured_bench_fault('unknown protected.bin')
            cli.do_measured_bench_fault('adc_error missing.bin')
            with patch('InkleySensor.verified_file',return_value=dict(format_version=2,bench_injection=True)):
                cli.do_measured_bench_fault('adc_error bench.bin')
        cli._bench_ready.assert_not_called()

    def test_all_fault_profiles_support_matching_ram_discard_and_block_ack_clear(self):
        for profile in (2,3,4):
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'recording.bin';path.write_bytes(fault_image(profile))
                cli=CANBusCommander();cli._bench_ready=Mock(return_value=True)
                cli._bench_stage=Mock(return_value=True);cli._recv_u32_response=Mock(return_value=0)
                with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_bench_discard(str(path))
                self.assertEqual(cli._bench_stage.call_args.args[1],RID)
                cli._flash_ready=Mock()
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.do_ack_flash(str(path));cli.do_clear_flash(str(path))
                cli._flash_ready.assert_not_called()

if __name__=='__main__':unittest.main()
