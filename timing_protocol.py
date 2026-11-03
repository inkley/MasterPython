"""CRC-protected volatile MCU timing snapshots (TIM1); no UTC or sample timestamps."""
import struct
import zlib

FIELDS = ('clock_hz now_ticks attempts completed adc_timeouts adc_errors '
          'first_ticks last_ticks min_interval_ticks max_interval_ticks interval_outside_10us '
          'estimated_missing_slots min_adc_path_ticks max_adc_path_ticks tx_queue_drops ram_overwrites '
          'rx_software_overruns rx_hardware_overruns tx_failures '
          'erase_calls erase_total_ticks erase_max_ticks program_calls program_total_ticks program_max_ticks '
          'unsafe_flash_rejections flash_errors storage_commands storage_kind storage_ticks storage_attempts '
          'storage_flash_calls min_systick_ticks max_systick_ticks systick_long_intervals diagnostic_mode').split()
WORD_COUNT = 6 + 2 * len(FIELDS)


def decode_snapshot(payload):
    if len(payload) != WORD_COUNT * 4:
        raise ValueError('Incomplete or unsupported timing snapshot length')
    magic, version, sequence, count, flags = struct.unpack_from('<5I', payload)
    if magic != 0x314D4954 or version != 1 or count != len(FIELDS) or flags != 3:
        raise ValueError('Unsupported timing snapshot header')
    if zlib.crc32(payload[:-4]) != struct.unpack_from('<I', payload, len(payload)-4)[0]:
        raise ValueError('Timing snapshot CRC mismatch')
    values = dict(zip(FIELDS, struct.unpack_from('<' + 'Q'*count, payload, 20)))
    if not values['clock_hz']:
        raise ValueError('Invalid timer clock')
    if values['attempts'] != values['completed'] + values['adc_timeouts'] + values['adc_errors']:
        raise ValueError('Incoherent acquisition counters')
    intervals = max(0, values['attempts']-1)
    rate = None
    if intervals and values['last_ticks'] > values['first_ticks']:
        rate = intervals * values['clock_hz'] / (values['last_ticks'] - values['first_ticks'])
    return {'schema': 'TIM1', 'sequence': sequence, 'flags': flags, 'counters': values,
            'pair_rate_hz': rate,
            'microseconds': {k: v*1e6/values['clock_hz'] for k,v in values.items()
                             if k.endswith('_ticks')},
            'limitations': ['System-clock-relative, not independent clock calibration or UTC.',
                           'Debugger halts count as elapsed time; do not halt during a run.',
                           'Intervals are software ADC-trigger intervals, not channel aperture measurements.',
                           'Missing slots are an estimate from intervals; CAN host delivery is not certified.',
                           'Flash runs with acquisition stopped; no continuous-flash result is implied.']}


def collect_words(frames, word_count):
    """Validate ordinal and payload size before accepting transport bytes."""
    if word_count != WORD_COUNT:
        raise ValueError('Unsupported timing word count')
    raw = bytearray()
    for ordinal, data in frames:
        if ordinal != len(raw)//4 or len(data) != 4 or ordinal >= word_count:
            raise ValueError('Missing, duplicate, or reordered timing word')
        raw.extend(data)
    if len(raw) != word_count*4:
        raise ValueError('Incomplete timing transfer')
    return bytes(raw)
