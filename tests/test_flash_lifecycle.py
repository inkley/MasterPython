"""Offline lifecycle reference/host tests; no C execution or real flash writes."""
import contextlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock,patch
import uuid
from flash_lifecycle import *
from .test_flash_recovery import fixture
from InkleySensor import CANBusCommander

SOURCE=fixture()
ID=SOURCE[2056:2072]
DIGEST=struct.unpack_from('<I',SOURCE,2048+1016)[0]
REQ=uuid.UUID('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee').bytes

def snapshot(op,gen=1,identity=ID,digest=DIGEST):
    return encode_journal(identity,digest,op,gen,REQ,120)

def with_journal(image,block,s):
    b=bytearray(image);b[block*1024:(block+1)*1024]=s;return bytes(b)

class LifecycleTests(unittest.TestCase):
    def test_ack_retains_data_and_clear_requires_ack(self):
        self.assertEqual(lifecycle_view(SOURCE)['state'],'COMMITTED')
        with self.assertRaises(ValueError):clear_plan(SOURCE,ID,DIGEST)
        image=with_journal(SOURCE,0,snapshot(1))
        self.assertEqual(image[2048:],SOURCE[2048:])
        self.assertEqual(lifecycle_view(image)['state'],'ACKNOWLEDGED')
        self.assertEqual(clear_plan(image,ID,DIGEST),[9,10,2])
    def test_delete_intent_and_every_clear_boundary(self):
        image=with_journal(with_journal(SOURCE,0,snapshot(1)),1,snapshot(2,2))
        self.assertEqual(lifecycle_view(image)['state'],'CLEAR_PENDING')
        for page in clear_plan(image,ID,DIGEST):
            for cut in range(0,1025,4):
                b=bytearray(image);b[page*1024:page*1024+cut]=b'\xff'*cut
                state=lifecycle_view(bytes(b))['state']
                self.assertIn(state,('CLEAR_PENDING','CLEARED'))
            b=bytearray(image);b[page*1024:(page+1)*1024]=b'\xff'*1024;image=bytes(b)
        self.assertEqual(lifecycle_view(image)['state'],'CLEARED')
        self.assertEqual(clear_plan(image,ID,DIGEST),[])
        self.assertEqual(decode_journal(image[1024:2048])['op'],2)
    def test_torn_ack_never_deletes_and_torn_delete_keeps_ack(self):
        for cut in range(0,1024,4):
            incomplete=snapshot(1)[:cut]+b'\xff'*(1024-cut)
            image=with_journal(SOURCE,0,incomplete)
            self.assertEqual(image[2048:],SOURCE[2048:])
            self.assertIn(lifecycle_view(image)['state'],('COMMITTED','JOURNAL_UNCERTAIN'))
        ack=with_journal(SOURCE,0,snapshot(1))
        for cut in range(0,1024,4):
            incomplete=snapshot(2,2)[:cut]+b'\xff'*(1024-cut)
            image=with_journal(ack,1,incomplete)
            self.assertEqual(lifecycle_view(image)['state'],'ACKNOWLEDGED')
            self.assertEqual(image[2048:],SOURCE[2048:])
    def test_stale_wrong_and_ram_identity_rejected(self):
        ack=with_journal(SOURCE,0,snapshot(1))
        for identity,digest in [(uuid.uuid4().bytes,DIGEST),(ID,DIGEST^1)]:
            with self.assertRaises(ValueError):clear_plan(ack,identity,digest)
        with self.assertRaises(ValueError):clear_plan(ack,ID,DIGEST,ram_retained=True)
    def test_new_capture_and_new_manifest_not_deleted_by_old_intent(self):
        deleted=with_journal(SOURCE,1,snapshot(2,2))
        new=bytearray(deleted)
        new_id=uuid.uuid4().bytes
        # Restore a different complete capture and recompute all identity-bound CRCs.
        for page in (9,10):
            start=page*1024;new[start+8:start+24]=new_id
            struct.pack_into('<I',new,start+1016,zlib.crc32(new[start:start+1016]))
        new[2056:2072]=new_id
        struct.pack_into('<I',new,2048+168,zlib.crc32(new[9*1024:11*1024]))
        struct.pack_into('<I',new,2048+1016,zlib.crc32(new[2048:3064]))
        new=bytes(new)
        self.assertEqual(lifecycle_view(new)['state'],'COMMITTED')
        with self.assertRaisesRegex(ValueError,'Newer'):clear_plan(new,ID,DIGEST)
        new_digest=struct.unpack_from('<I',new,3064)[0]
        newer=with_journal(new,0,snapshot(1,3,new_id,new_digest))
        self.assertEqual(lifecycle_view(newer)['state'],'ACKNOWLEDGED')
    def test_stale_clear_cannot_destroy_new_partial_capture(self):
        image=bytearray(b'\xff'*131072)
        image[1024:2048]=snapshot(2,2)
        for prefix in (b'I',b'IP',b'IPL',b'IPLG',b'IPLG'+b'\0'*30):
            b=bytearray(image);b[9*1024:9*1024+len(prefix)]=prefix
            with self.assertRaises(ValueError):clear_plan(bytes(b),ID,DIGEST)
            self.assertEqual(lifecycle_view(bytes(b))['state'],'INCOMPLETE_DAMAGED_OR_UNSUPPORTED')

    def test_journal_corruption_and_conflicting_generation(self):
        a=snapshot(1)
        for offset in range(1024):
            b=bytearray(a);b[offset]^=1
            with self.assertRaises(JournalError):decode_journal(bytes(b))
        image=with_journal(with_journal(SOURCE,0,a),1,snapshot(2,1))
        with self.assertRaises(JournalError):latest_journal(image)
    def test_unknown_extra_block_prevents_clear(self):
        image=bytearray(with_journal(SOURCE,0,snapshot(1)));image[7*1024]=0
        with self.assertRaises(ValueError):clear_plan(bytes(image),ID,DIGEST)
    def test_host_verification_flush_and_no_file_change(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'recording.bin';p.write_bytes(SOURCE)
            with patch('flash_lifecycle.os.fsync') as sync:
                info=verified_file(p);sync.assert_called_once()
            self.assertEqual(info['recording_id'].bytes,ID);self.assertEqual(p.read_bytes(),SOURCE)
    def test_host_gating_and_id_words(self):
        with contextlib.redirect_stdout(io.StringIO()):cli=CANBusCommander()
        cli._flash_ready=Mock(return_value=True);cli._flash_capability=0x49500103
        cli._recv_u32_response=Mock(side_effect=[0]*8+[120])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'recording.bin';p.write_bytes(SOURCE)
            with contextlib.redirect_stdout(io.StringIO()):cli.do_ack_flash(str(p))
        calls=cli._recv_u32_response.call_args_list
        self.assertEqual([c.args[0] for c in calls],list(range(0x20,0x28))+[0x28])
        staged=b''.join(c.kwargs['value_u32'].to_bytes(4,'big') for c in calls[4:8])
        self.assertEqual(staged,ID);self.assertEqual(calls[-1].kwargs['value_u32'],DIGEST)
        cli._recv_u32_response.reset_mock()
        with contextlib.redirect_stdout(io.StringIO()):cli.do_clear_flash('does-not-exist.bin')
        cli._recv_u32_response.assert_not_called()
    def test_old_firmware_never_receives_lifecycle_mutation(self):
        with contextlib.redirect_stdout(io.StringIO()):cli=CANBusCommander()
        cli._flash_ready=Mock(return_value=True);cli._flash_capability=0x49500102;cli._recv_u32_response=Mock()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'recording.bin';p.write_bytes(SOURCE)
            with contextlib.redirect_stdout(io.StringIO()):cli.do_clear_flash(str(p))
        cli._recv_u32_response.assert_not_called()

if __name__=='__main__':unittest.main()
