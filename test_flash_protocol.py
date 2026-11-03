"""Offline flash protocol tests; no hardware or serial port access."""
import contextlib
import io
import struct
import unittest
import zlib
from unittest.mock import Mock
import can
from flash_protocol import manifest_info, validate_recording
from InkleySensor import CANBusCommander

UID=bytes.fromhex('00112233445546778899aabbccddeeff')
def block(kind,seq,count,payload,slot=0):
    h=struct.pack('<4sHH16sIHHQQI12s',b'IPLG',1,kind,UID,seq,count,10,slot,slot*1000,1000,bytes(12))
    body=h+payload+b'\xff'*(952-len(payload))
    return body+struct.pack('<I',zlib.crc32(body))+b'CMIT'

def recording(count=120):
    data=[]
    for base in range(0,count,119):
        n=min(119,count-base)
        data.append(block(1,len(data),n,b''.join(struct.pack('<IHH',i*1000,(base+i)%4096,2345) for i in range(n)),base))
    p=bytearray(128)
    struct.pack_into('<QQ',p,40,count,count)
    struct.pack_into('<QQ',p,80,count-1,count*1000)
    struct.pack_into('<5I',p,96,len(data),0,zlib.crc32(b''.join(data)),0xc1,3)
    struct.pack_into('<I',p,124,1)
    return block(3,len(data),1,p),data

class FlashTests(unittest.TestCase):
    def cli(self):
        with contextlib.redirect_stdout(io.StringIO()): return CANBusCommander()
    def test_manifest_and_full_recording(self):
        for n in (1,119,120,1000,4094):
            m,d=recording(n)
            self.assertEqual(manifest_info(m)[0],n)
            self.assertEqual(len(validate_recording(m,d)),n)
    def test_corrupt_missing_reordered_and_cross_session(self):
        m,d=recording()
        for candidate in (d[:-1],d[::-1],[d[0],d[0]]):
            with self.assertRaises(ValueError): validate_recording(m,candidate)
        bad=bytearray(d[0]);bad[100]^=1
        with self.assertRaises(ValueError): validate_recording(m,[bytes(bad),d[1]])
        bad=bytearray(d[0]);bad[8]^=1;struct.pack_into('<I',bad,1016,zlib.crc32(bad[:1016]))
        with self.assertRaises(ValueError): validate_recording(m,[bytes(bad),d[1]])
    def test_incomplete_manifest(self):
        m,d=recording()
        with self.assertRaises(ValueError): validate_recording(m[:-4]+b'\xff'*4,d)
    def test_failed_start_does_not_launch_logger(self):
        cli=self.cli();cli._recv_u32_response=Mock(return_value=0x80000002)
        with contextlib.redirect_stdout(io.StringIO()): cli.do_start('')
        self.assertFalse(cli.streaming);self.assertIsNone(cli.stream_thread)
    def test_capture_uuid_and_limit(self):
        cli=self.cli();cli._flash_ready=Mock(return_value=True)
        cli._recv_u32_response=Mock(side_effect=[0,0,0,0,1000])
        with contextlib.redirect_stdout(io.StringIO()): cli.do_flash_capture('1000')
        self.assertEqual([x.args[0] for x in cli._recv_u32_response.call_args_list],[16,17,18,19,20])
        self.assertEqual(cli._recv_u32_response.call_args_list[-1].kwargs['value_u32'],1000)
    def test_recovery_gates_scratch_writes_on_old_firmware(self):
        cli=self.cli();cli._flash_ready=Mock(return_value=True);cli._flash_capability=0x49500101
        cli._recv_u32_response=Mock()
        with contextlib.redirect_stdout(io.StringIO()): cli.do_flash_scratch('erase')
        cli._recv_u32_response.assert_not_called()
    def test_scratch_address_is_not_host_selectable(self):
        cli=self.cli();cli._recovery_ready=Mock(return_value=True);cli._recv_u32_response=Mock(return_value=0)
        with contextlib.redirect_stdout(io.StringIO()): cli.do_flash_scratch('erase')
        cli._recv_u32_response.assert_called_once_with(0x1c,timeout=30,value_u32=0x53524305)
        cli._recv_u32_response.reset_mock()
        with contextlib.redirect_stdout(io.StringIO()): cli.do_flash_scratch('erase 2')
        cli._recv_u32_response.assert_not_called()

    def test_block_read_order(self):
        cli=self.cli();cli._drain_pending_can_messages=Mock();cli._recv_u32_response=Mock(return_value=256)
        cli.bus=Mock()
        cli._recv_frame=Mock(side_effect=[can.Message(arbitration_id=0x108,data=[8,seq>>8,seq&255,0x1a,1,2,3,4]) for seq in range(256)])
        self.assertEqual(cli._flash_read_block(2),bytes([1,2,3,4])*256)
        cli._recv_frame=Mock(return_value=can.Message(arbitration_id=0x108,data=[8,0,1,0x1a,1,2,3,4]))
        with self.assertRaisesRegex(ValueError,'Dropped'):cli._flash_read_block(2)

if __name__=='__main__':unittest.main()
