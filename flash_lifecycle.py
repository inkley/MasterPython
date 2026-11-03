"""Host evidence and offline reference journal model. No MCU writes here."""
import os
from pathlib import Path
import struct
import uuid
import zlib
from flash_protocol import validate_recording, manifest_info, recover_partition

class JournalError(ValueError): pass

def verified_file(path):
    """Validate the exact file read, then request OS flush before acknowledging it."""
    with Path(path).open('r+b') as handle:
        data=handle.read()
        if len(data)!=131072: raise ValueError('Expected reconstructed 128 KiB recording binary')
        m=data[2048:3072]
        bench=False
        if m[4:6]==b'\x02\0':
            from flash_v2 import decode_recording
            record=decode_recording(data);count=record['summary']['samples'];bench=record['metadata']['schema']==2
        else:
            count,n,_=manifest_info(m)
            validate_recording(m,[data[(9+i)*1024:(10+i)*1024] for i in range(n)])
        handle.flush()
        os.fsync(handle.fileno())
    return dict(recording_id=uuid.UUID(bytes=m[8:24]),manifest_crc=struct.unpack_from('<I',m,1016)[0],count=count,format_version=int.from_bytes(m[4:6],'little'),bench_injection=bench)

def decode_journal(block):
    if len(block)!=1024 or block[:8]!=b'IPLG\x01\0\x04\0' or block[1020:]!=b'CMIT':
        raise JournalError('Incomplete or unsupported journal')
    if zlib.crc32(block[:1016])!=struct.unpack_from('<I',block,1016)[0]:raise JournalError('Journal CRC')
    seq,count,flags=struct.unpack_from('<IHH',block,24)
    if count!=1 or flags!=2 or block[32:48]!=bytes(16) or struct.unpack_from('<I',block,48)[0]!=1000 or block[52:64]!=bytes(12):
        raise JournalError('Journal header')
    identity=block[64:80];digest,op,rf,generation=struct.unpack_from('<IHHQ',block,80)
    request=block[96:112];n,pairs=struct.unpack_from('<II',block,112)
    if identity==bytes(16) or identity!=block[8:24] or request==bytes(16) or rf or not generation or seq!=generation&0xffffffff:
        raise JournalError('Journal identity/generation')
    if op not in (1,2) or not 1<=pairs<=4094 or n!=(pairs+118)//119 or block[120:128]!=bytes(8) or block[128:1016]!=b'\xff'*888:
        raise JournalError('Journal payload')
    return dict(identity=identity,digest=digest,op=op,generation=generation,request=request,blocks=n,pairs=pairs)

def encode_journal(identity,digest,op,generation,request,pairs):
    payload=struct.pack('<16sIHHQ16sII8s',identity,digest,op,0,generation,request,(pairs+118)//119,pairs,bytes(8))
    header=struct.pack('<4sHH16sIHHQQI12s',b'IPLG',1,4,identity,generation&0xffffffff,1,2,0,0,1000,bytes(12))
    body=header+payload+b'\xff'*888
    result=body+struct.pack('<I',zlib.crc32(body))+b'CMIT'
    decode_journal(result)
    return result

def latest_journal(image):
    valid=[]; nonblank=False
    for i in range(2):
        block=image[i*1024:(i+1)*1024]
        nonblank |= block!=b'\xff'*1024
        try: valid.append((i,decode_journal(block)))
        except JournalError: pass
    if not valid:
        if nonblank: raise JournalError('No valid journal snapshot; retain media read-only')
        return None
    valid.sort(key=lambda x:x[1]['generation'])
    if len(valid)==2 and valid[0][1]['generation']==valid[1][1]['generation'] and image[:1024]!=image[1024:2048]:
        raise JournalError('Conflicting journal generation')
    return valid[-1]

def footprint_safe(image,identity,n):
    if not 1<=n<=(4094+118)//119:return False
    m=image[2048:3072]
    try:
        _,actual_n,_=manifest_info(m)
        matches=m[8:24]==identity and actual_n==n
    except ValueError:matches=False
    if not matches and image[9*1024:(9+n)*1024]!=b'\xff'*(n*1024):return False
    for i in range(2,128):
        b=image[i*1024:(i+1)*1024]
        owned=i==2 or 9<=i<9+n
        if not owned and b!=b'\xff'*1024:return False
        if owned and b[:4]==b'IPLG' and b[8:24]!=identity:return False
    return True

def lifecycle_view(image):
    if len(image)!=131072:raise ValueError('Wrong image size')
    baseline=recover_partition(image)
    try: newest=latest_journal(image)
    except JournalError:return dict(state='JOURNAL_UNCERTAIN',samples=baseline['samples'])
    j=newest[1] if newest else None
    valid=baseline['samples']>0
    m=image[2048:3072]
    if valid:
        if j and j['identity']==m[8:24] and j['digest']==struct.unpack_from('<I',m,1016)[0]:
            return dict(state='ACKNOWLEDGED' if j['op']==1 else 'CLEAR_PENDING',samples=baseline['samples'])
        extra=[i for i in range(2,128) if i!=2 and not 9<=i<9+(baseline['samples']+118)//119 and image[i*1024:(i+1)*1024]!=b'\xff'*1024]
        return dict(state='COMMITTED_WITH_QUARANTINE' if extra else 'COMMITTED',samples=baseline['samples'])
    if j and j['op']==2:
        if image[2048:]==b'\xff'*(131072-2048):return dict(state='CLEARED',samples=0)
        if footprint_safe(image,j['identity'],j['blocks']):return dict(state='CLEAR_PENDING',samples=0)
    return dict(state=baseline['state'],samples=baseline['samples'])

def clear_plan(image, identity, digest, ram_retained=False):
    """Offline reference preflight only; does not execute a clear or write intent."""
    if ram_retained: raise ValueError('New RAM recording is retained')
    found=latest_journal(image)
    if found is None: raise ValueError('ACK required')
    j=found[1]
    m=image[2048:3072]
    baseline=recover_partition(image)
    if j['identity']!=identity or j['digest']!=digest:raise ValueError('Stale identity')
    if baseline['samples']:
        if m[8:24]!=identity or struct.unpack_from('<I',m,1016)[0]!=digest:raise ValueError('Newer recording retained')
    elif j['op']!=2: raise ValueError('Missing committed record')
    if not footprint_safe(image,identity,j['blocks']):raise ValueError('Foreign/unallocated data protected')
    if j['op']==2 and image[2048:]==b'\xff'*(131072-2048):return []
    return list(range(9,9+j['blocks']))+[2]
