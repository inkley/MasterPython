"""Read-only validation of stage-one nominal flash recordings; no hardware access."""
import struct
import zlib

BLOCK_SIZE=1024

def validate_block(data, kind=None):
    if len(data)!=1024 or data[:4]!=b'IPLG' or data[4:6]!=b'\x01\0' or data[1020:]!=b'CMIT':
        raise ValueError('Incomplete or unsupported block')
    if struct.unpack_from('<I',data,1016)[0] != zlib.crc32(data[:1016]):
        raise ValueError('Block CRC mismatch')
    version_kind=struct.unpack_from('<H',data,6)[0]
    if kind is not None and version_kind!=kind: raise ValueError('Wrong block kind')
    if data[8:24]==bytes(16) or data[52:64]!=bytes(12): raise ValueError('Invalid identity/reserved fields')
    if struct.unpack_from('<I',data,48)[0]!=1000 or struct.unpack_from('<H',data,30)[0]!=10:
        raise ValueError('Not a stage-one nominal/degraded recording')
    return data

def manifest_info(data):
    validate_block(data,3)
    count=struct.unpack_from('<Q',data,104)[0]
    blocks,events,stream_crc,quality,reason=struct.unpack_from('<5I',data,160)
    if not 0<count<=4094 or blocks!=(count+118)//119 or events!=0 or quality!=0xc1 or reason not in (1,3):
        raise ValueError('Invalid stage-one manifest')
    if struct.unpack_from('<H',data,28)[0]!=1 or struct.unpack_from('<I',data,24)[0]!=blocks or struct.unpack_from('<I',data,188)[0]!=1:
        raise ValueError('Invalid manifest sequence/schema')
    if data[192:1016]!=b'\xff'*824: raise ValueError('Invalid manifest padding')
    return count,blocks,stream_crc

def validate_recording(manifest,blocks):
    count,n,expected_crc=manifest_info(manifest)
    if len(blocks)!=n: raise ValueError('Missing data blocks')
    crc=0; samples=[]
    for seq,block in enumerate(blocks):
        validate_block(block,1)
        amount=struct.unpack_from('<H',block,28)[0]
        first_slot,first_us=struct.unpack_from('<QQ',block,32)
        if block[8:24]!=manifest[8:24] or struct.unpack_from('<I',block,24)[0]!=seq:
            raise ValueError('Session/sequence mismatch')
        if first_slot!=len(samples) or first_us!=first_slot*1000 or amount!=min(119,count-len(samples)):
            raise ValueError('Sample count/index mismatch')
        for i in range(amount):
            delta,p1,p2=struct.unpack_from('<IHH',block,64+i*8)
            if delta!=i*1000 or p1>4095 or p2>4095: raise ValueError('Invalid sample')
            samples.append((first_slot+i,p1,p2))
        end=64+amount*8
        if block[end:1016]!=b'\xff'*(1016-end): raise ValueError('Invalid padding')
        crc=zlib.crc32(block,crc)
    if len(samples)!=count or crc!=expected_crc: raise ValueError('Recording CRC/count mismatch')
    attempts,timeouts=struct.unpack_from('<QQ',manifest,112)
    other=struct.unpack_from('<Q',manifest,180)[0]
    if attempts!=count or timeouts or other: raise ValueError('Unaccounted acquisition failure')
    if struct.unpack_from('<QQ',manifest,136)!=(0,count-1): raise ValueError('Invalid first/last slot')
    return samples
