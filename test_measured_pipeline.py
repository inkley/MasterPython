"""Measured host integration with synthetic v2 images. No hardware access."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid
import numpy as np
import flash_v2 as v
from test_flash_v2 import fixture, image, RID, DOMAIN
from measured_export import download_v2, export_v2
from measured_time import load_measured_time, break_plot
from flash_lifecycle import verified_file
from InkleySensor import CANBusCommander
import analyze_pressure


class MeasuredTests(unittest.TestCase):
    def test_read_export_and_ack_evidence(self):
        raw=image(n=1024,start=2**60)
        read=Mock(side_effect=lambda p:raw[p*1024:(p+1)*1024])
        self.assertEqual(download_v2(read),raw)
        self.assertEqual(read.call_args_list[0].args,(2,))
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'export';meta=export_v2(raw,folder,'MCU_RAM')
            info=verified_file(folder/'recording.bin')
            self.assertEqual(info['count'],1024);self.assertEqual(info['format_version'],2)
            self.assertEqual(meta['time_domain_id'],str(DOMAIN))
            adc,index,_,_=analyze_pressure.load_csv(folder/'samples.csv')
            timing=load_measured_time(folder/'samples.csv',index)
            self.assertEqual(timing['ticks'][0],2**60)
            self.assertAlmostEqual(timing['t'][1],.001)
            self.assertTrue(timing['uniform'])
            self.assertFalse(timing['gap'].any())
            self.assertEqual(adc[0,0],0)

    def test_incomplete_or_foreign_download_rejected(self):
        raw=image(n=58)
        with self.assertRaises(ValueError):download_v2(lambda p:raw[p*1024:(p+1)*1024][:-4])
        other=v.encode_recording(uuid.uuid4(),uuid.uuid4(),*fixture())
        def read(p):return (other if p==10 else raw)[p*1024:(p+1)*1024]
        with self.assertRaises(ValueError):download_v2(read)

    def test_cli_flash_dump_dispatches_v2_without_ack_or_clear(self):
        raw=image(n=58)
        cli=CANBusCommander();cli._flash_ready=Mock(return_value=True)
        cli._flash_read_block=Mock(side_effect=lambda p:raw[p*1024:(p+1)*1024])
        cli._recv_u32_response=Mock()
        with tempfile.TemporaryDirectory() as temp:
            cli.output_dir=Path(temp)
            with contextlib.redirect_stdout(io.StringIO()):cli.do_dump_flash('measured')
            folder=next(Path(temp).iterdir())
            self.assertEqual((folder/'recording.bin').read_bytes(),raw)
            self.assertEqual(json.loads((folder/'recording_metadata.json').read_text())['origin'],'MCU_FLASH')
        cli._recv_u32_response.assert_not_called()

    def test_v2_ack_on_old_firmware_is_rejected_before_staging(self):
        cli=CANBusCommander();cli._flash_ready=Mock(return_value=True)
        cli._measured_ready=Mock(return_value=False);cli._recv_u32_response=Mock()
        evidence=dict(recording_id=RID,count=58,manifest_crc=1,format_version=2)
        with patch('InkleySensor.verified_file',return_value=evidence),contextlib.redirect_stdout(io.StringIO()):
            cli.do_ack_flash('saved.bin')
        cli._recv_u32_response.assert_not_called()

    def test_gap_plot_retains_both_endpoints(self):
        t,y=break_plot(np.array([0.,.001,.004]),np.array([1.,2.,3.]),np.array([False,False,True]))
        self.assertEqual(len(t),4);self.assertTrue(np.isnan(t[2]))
        self.assertEqual(y[1],2);self.assertEqual(y[3],3)

    def test_loader_rejects_domain_mix_and_silent_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'export';export_v2(image(n=3),folder,'OFFLINE')
            path=folder/'samples.csv'
            with path.open(newline='') as f:
                reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
            def write():
                with path.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            rows[1]['TimeDomainId']=str(uuid.uuid4());write()
            with self.assertRaises(ValueError):load_measured_time(path,np.arange(3))
            rows[1]['TimeDomainId']=rows[0]['TimeDomainId']
            rows[2]['TriggerTicks']=str(int(rows[2]['TriggerTicks'])+10000);write()
            with self.assertRaisesRegex(ValueError,'Unreported'):load_measured_time(path,np.arange(3))

    def test_legacy_csv_still_nominal(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'legacy.csv';p.write_text('Timestamp,SampleIndex,Pressure1,Pressure2\n,0,1,2\n,1,3,4\n')
            self.assertIsNone(load_measured_time(p,np.arange(2)))

    def test_old_capability_does_not_stage_uuid(self):
        cli=CANBusCommander();cli._flash_ready=Mock(return_value=True)
        cli._recv_u32_response=Mock(return_value=0x80000002)
        with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_capture('1000')
        cli._recv_u32_response.assert_called_once_with(0x30,value_u32=0)

    def test_reconnect_queries_existing_domain_without_assignment(self):
        cli=CANBusCommander();cli._measured_ready=Mock(return_value=True)
        cli._measured_domain=Mock(return_value=DOMAIN);cli._recv_u32_response=Mock()
        with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_init('')
        cli._recv_u32_response.assert_not_called()
        self.assertEqual(cli._measured_domain_id,DOMAIN)

    def test_domain_uuid_high_bit_words_are_not_error_codes(self):
        cli=CANBusCommander()
        words=[int.from_bytes(DOMAIN.bytes[i:i+4],'big') for i in range(0,16,4)]
        cli._recv_u32_response=Mock(side_effect=[1,*words,1])
        self.assertEqual(cli._measured_domain(),DOMAIN)

    def test_terminal_adc_event_is_available_for_plot_annotation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fault'
            export_v2(image(n=58,timeout=True),path,'OFFLINE')
            timing=load_measured_time(path/'samples.csv',np.arange(58))
            self.assertEqual(len(timing['event_times']),1)
            self.assertGreater(timing['event_times'][0],timing['t'][-1])

    def test_staging_mismatch_stops_handshake(self):
        cli=CANBusCommander();cli._measured_ready=Mock(return_value=True)
        cli._measured_domain=Mock(return_value=None);cli._recv_u32_response=Mock(return_value=None)
        with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_init('')
        self.assertEqual(cli._recv_u32_response.call_count,1)

    def test_capture_token_binds_recording_domain_and_limit(self):
        import zlib
        cli=CANBusCommander()
        def initialize(arg):cli._measured_domain_id=DOMAIN
        cli.do_measured_init=Mock(side_effect=initialize)
        def response(command,**kwargs):
            if command==0x38:return kwargs['value_u32']
            if command==0x36:return 1024
            return 0
        cli._recv_u32_response=Mock(side_effect=response)
        with patch('InkleySensor.uuid.uuid4',return_value=RID),contextlib.redirect_stdout(io.StringIO()):
            cli.do_measured_capture('1024')
        calls=cli._recv_u32_response.call_args_list
        self.assertEqual([c.args[0] for c in calls],[0x10,0x11,0x12,0x13,0x38,0x36])
        self.assertEqual(calls[-2].kwargs['value_u32'],zlib.crc32(RID.bytes+DOMAIN.bytes+(1024).to_bytes(4,'big')))

    def test_capture_arm_failure_does_not_start(self):
        cli=CANBusCommander()
        cli.do_measured_init=Mock(side_effect=lambda _:setattr(cli,'_measured_domain_id',DOMAIN))
        cli._recv_u32_response=Mock(side_effect=[0,0,0,0,None])
        with contextlib.redirect_stdout(io.StringIO()):cli.do_measured_capture('1024')
        self.assertNotIn(0x36,[c.args[0] for c in cli._recv_u32_response.call_args_list])

    def test_measured_plot_uses_time_and_disables_irregular_filter(self):
        s,e,meta,m=fixture(n=58)
        # One integer tick of jitter: valid acquisition, nonuniform data must not
        # silently enter a uniform-grid IIR filter.
        s[1]['trigger_ticks']+=1
        raw=v.encode_recording(RID,DOMAIN,s,e,meta,m)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'source';out=Path(temp)/'analysis'
            export_v2(raw,folder,'OFFLINE')
            with patch.object(sys,'argv',['analyze_pressure.py',str(folder/'samples.csv'),'--outdir',str(out)]),contextlib.redirect_stdout(io.StringIO()):
                analyze_pressure.main()
            result=json.loads((out/'metadata.json').read_text())
            self.assertIsNone(result['lowpass_hz']);self.assertIsNone(result['utc'])
            self.assertIn('RAW_TRIGGER_TICKS',result['time_basis'])
            self.assertTrue((out/'pressure.png').exists())
            with np.load(out/'processed.npz') as npz:
                self.assertEqual(int(npz['trigger_ticks'][1]),s[1]['trigger_ticks'])
                self.assertAlmostEqual(float(npz['t'][1]),.00100005)


if __name__=='__main__':unittest.main()
