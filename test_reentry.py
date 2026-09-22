"""Offline regression checks; no serial ports or sensor hardware are opened."""
import contextlib
import datetime
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import can
import numpy as np

from InkleySensor import CANBusCommander, packed_sample_timestamps
from analyze_pressure import load_csv, process


class ReentryTests(unittest.TestCase):
    def test_packed_spacing_and_day_boundary(self):
        receipt = datetime.datetime(2026, 9, 22)
        a, b = packed_sample_timestamps(receipt)
        self.assertEqual(b, receipt)
        self.assertEqual((b-a).total_seconds(), 0.001)
        self.assertEqual(a.day, 21)

    def test_version_survives_malformed_frame(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            cli = CANBusCommander()
            cli.bus = Mock()
            cli.bus.recv.side_effect = [ValueError('invalid hex'), can.Message(
                arbitration_id=0x108, data=[8, 1, 7, 1, 0, 0, 3, 236])]
            cli.do_version('')
        self.assertEqual(cli.version, '0.0.3.236')
        self.assertIn('possible data loss', output.getvalue())

    def test_transport_failure_is_not_hidden(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cli = CANBusCommander()
        cli.bus = Mock()
        cli.bus.recv.side_effect = can.CanOperationError('disconnected')
        with self.assertRaises(can.CanOperationError):
            cli._recv_frame(0.1)

    def test_dump_time_and_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dump.csv'
            path.write_text('Timestamp,SampleIndex,Pressure1,Pressure2\n'
                            'same,0,0,4095\nsame,1,4095,0\n')
            adc, index, timestamps, has_index = load_csv(path)
        result = process(adc, index, cutoff=None,
                         calibration={'P1': {'m': 2, 'b': 0.1}, 'P2': {'m': 1, 'b': 0}})
        self.assertTrue(has_index)
        self.assertEqual(timestamps, ['same', 'same'])
        np.testing.assert_allclose(result['t'], [0, .001])
        np.testing.assert_allclose(result['p1'], [-.05, 1.6])
        np.testing.assert_allclose(result['dp'], [-3.35, 1.6])

    def test_filter_rejects_gaps_and_short_records(self):
        with self.assertRaisesRegex(ValueError, 'missing sample'):
            process(np.ones((100, 2)), np.arange(100)*2)
        with self.assertRaisesRegex(ValueError, 'too short'):
            process(np.ones((2, 2)), np.arange(2))

    def test_lowpass_preserves_dc_and_attenuates_high_frequency(self):
        index = np.arange(4000)
        signal = 2000 + 100*np.sin(2*np.pi*200*index/1000)
        result = process(np.column_stack((signal, signal)), index)
        filtered = result['p1_f'][200:-200]
        self.assertLess(np.std(filtered), .001)
        self.assertAlmostEqual(np.mean(filtered), 2000*3.3/4095, places=5)


if __name__ == '__main__':
    unittest.main()
