"""Synthetic interrupted-write/erase and corruption tests; no physical flash access."""
import unittest
from .test_flash_protocol import recording
from flash_protocol import recover_partition

SIZE=131072

def fixture():
    m,d=recording(120)
    image=bytearray(b'\xff'*SIZE)
    image[2048:3072]=m
    for i,b in enumerate(d): image[(9+i)*1024:(10+i)*1024]=b
    return bytes(image)

class RecoveryTests(unittest.TestCase):
    def test_blank_and_good(self):
        self.assertEqual(recover_partition(b'\xff'*SIZE)['state'],'EMPTY')
        self.assertEqual(recover_partition(fixture())['samples'],120)
    def test_every_program_boundary(self):
        image=fixture()
        # Model DATA blocks followed by manifest, each programmed prefix incl commit.
        writes=[(9*1024,image[9*1024:10*1024]),(10*1024,image[10*1024:11*1024]),(2048,image[2048:3072])]
        prior=bytearray(b'\xff'*SIZE)
        for address,data in writes:
            for cut in range(0,1024,4):
                partial=bytearray(prior);partial[address:address+cut]=data[:cut]
                self.assertNotIn(recover_partition(bytes(partial))['state'],('COMMITTED','COMMITTED_WITH_QUARANTINE'))
            prior[address:address+1024]=data
        self.assertEqual(recover_partition(bytes(prior))['samples'],120)
    def test_every_bit_of_committed_data_and_manifest(self):
        source=fixture()
        for block in (2,9,10):
            for offset in range(1024):
                for bit in range(8):
                    image=bytearray(source);image[block*1024+offset]^=1<<bit
                    self.assertEqual(recover_partition(bytes(image))['state'],'INCOMPLETE_DAMAGED_OR_UNSUPPORTED')
    def test_scratch_interrupted_erase_preserves_committed(self):
        source=fixture()
        for cut in range(0,1025,4):
            image=bytearray(source)
            image[7*1024:8*1024]=bytes(1024)
            image[7*1024:7*1024+cut]=b'\xff'*cut
            result=recover_partition(bytes(image))
            self.assertEqual(result['samples'],120)
            self.assertEqual(result['quarantine'],[] if cut==1024 else [7])
            self.assertEqual(image[2048:3072],source[2048:3072])
    def test_erasing_protected_record_is_not_recovered_as_complete(self):
        source=fixture()
        for block in (2,9,10):
            for cut in (4,64,512,1024):
                image=bytearray(source);image[block*1024:block*1024+cut]=b'\xff'*cut
                self.assertEqual(recover_partition(bytes(image))['state'],'INCOMPLETE_DAMAGED_OR_UNSUPPORTED')
    def test_scattered_erase_and_unknown_media(self):
        image=bytearray(fixture());image[7*1024:8*1024]=bytes([0xaa,0xff])*512
        self.assertEqual(recover_partition(bytes(image))['quarantine'],[7])
        image=bytearray(b'\xff'*SIZE);image[0]=0
        self.assertEqual(recover_partition(bytes(image))['state'],'INCOMPLETE_DAMAGED_OR_UNSUPPORTED')
    def test_real_retained_recording_copy_when_available(self):
        from pathlib import Path
        path=Path('Data/flash_after_reboot_01_20261102_133752_933305/recording.bin')
        if not path.exists(): self.skipTest('local bench artifact unavailable')
        original=path.read_bytes()
        self.assertEqual(recover_partition(original)['samples'],1000)
        for state in (b'\x00'*1024,b'\xff'*512+b'\x00'*512):
            changed=bytearray(original);changed[7168:8192]=state
            self.assertEqual(recover_partition(bytes(changed))['samples'],1000)
            self.assertEqual(recover_partition(bytes(changed))['quarantine'],[7])
        self.assertEqual(path.read_bytes(),original) # original file never modified

    def test_invalid_size(self):
        with self.assertRaises(ValueError):recover_partition(bytes(1024))

if __name__=='__main__':unittest.main()
