"""Timing transport integrity and CLI routing; offline, no hardware timing claim."""
import contextlib
import io
import struct
import unittest
import zlib
from unittest.mock import Mock
from timing_protocol import FIELDS, WORD_COUNT, collect_words, decode_snapshot
from InkleySensor import CANBusCommander


def packet(**overrides):
    values = dict.fromkeys(FIELDS, 0)
    values.update(clock_hz=20000000, attempts=1001, completed=1001,
                  first_ticks=100, last_ticks=20000100,
                  min_interval_ticks=20000, max_interval_ticks=20000)
    values.update(overrides)
    data = struct.pack('<5I', 0x314D4954, 1, 9, len(FIELDS), 3)
    data += struct.pack('<'+'Q'*len(FIELDS), *(values[k] for k in FIELDS))
    return data + struct.pack('<I', zlib.crc32(data))


class TimingTests(unittest.TestCase):
    def test_rate_units_and_64bit_timer(self):
        r = decode_snapshot(packet(now_ticks=2**40))
        self.assertEqual(r['pair_rate_hz'], 1000)
        self.assertEqual(r['microseconds']['min_interval_ticks'], 1000)
        self.assertEqual(r['counters']['now_ticks'], 2**40)

    def test_crc_and_truncation(self):
        raw = packet()
        for cut in range(0,len(raw),4):
            with self.assertRaises(ValueError): decode_snapshot(raw[:cut])
        for offset in range(len(raw)):
            broken = bytearray(raw); broken[offset] ^= 1
            with self.assertRaises(ValueError): decode_snapshot(bytes(broken))

    def test_counter_consistency(self):
        with self.assertRaises(ValueError): decode_snapshot(packet(adc_timeouts=1))
        self.assertEqual(decode_snapshot(packet(completed=999,adc_timeouts=1,adc_errors=1))['counters']['attempts'],1001)
        with self.assertRaises(ValueError): decode_snapshot(packet(clock_hz=0))

    def test_transport_loss_reorder_duplicate(self):
        raw = packet(); frames = [(i,raw[4*i:4*i+4]) for i in range(WORD_COUNT)]
        self.assertEqual(collect_words(frames,WORD_COUNT),raw)
        for invalid in (frames[:-1],frames[1:],frames[:3]+frames[2:],frames[::-1]):
            with self.assertRaises(ValueError): collect_words(invalid,WORD_COUNT)
        with self.assertRaises(ValueError): collect_words(frames,WORD_COUNT+1)

    def test_stop_waits_for_response_before_closing_reader(self):
        cli = CANBusCommander(); cli.streaming=True; cli.stream_thread=Mock()
        cli._timing_ready=Mock(return_value=True)
        def response(*args,**kwargs):
            self.assertTrue(cli.streaming)
            cli.stream_thread.join.assert_not_called()
            return 0
        cli._recv_u32_response=Mock(side_effect=response)
        with contextlib.redirect_stdout(io.StringIO()): cli.do_timing_stop('')
        self.assertFalse(cli.streaming)
        cli.stream_thread.join.assert_called_once()

    def test_failed_stop_does_not_claim_or_close(self):
        cli = CANBusCommander();cli.streaming=True;cli.stream_thread=Mock()
        cli._timing_ready=Mock(return_value=True);cli._recv_u32_response=Mock(return_value=None)
        with contextlib.redirect_stdout(io.StringIO()): cli.do_timing_stop('')
        self.assertTrue(cli.streaming);cli.stream_thread.join.assert_not_called()

    def test_old_firmware_does_not_start_diagnostics(self):
        cli = CANBusCommander();cli.initialize_can_bus=Mock(return_value=True)
        cli._drain_pending_can_messages=Mock();cli._recv_u32_response=Mock(return_value=0x49500103)
        with contextlib.redirect_stdout(io.StringIO()): cli.do_timing_start('idle')
        cli._recv_u32_response.assert_called_once_with(0x0f)

if __name__ == '__main__': unittest.main()
