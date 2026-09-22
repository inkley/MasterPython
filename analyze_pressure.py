"""Python quick-look equivalent of IPS_TI_Raw_v19.m, with buffer CSV support."""

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import numpy as np
from scipy.io import savemat
from scipy.signal import butter, sosfiltfilt


def load_csv(path):
    """Keep row order and original timestamps; never silently discard bad data."""
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if not {'Timestamp', 'Pressure1', 'Pressure2'} <= set(reader.fieldnames or []):
            raise ValueError('Expected Timestamp, Pressure1, Pressure2 columns')
        rows = list(reader)
        has_index = 'SampleIndex' in reader.fieldnames
    if not rows:
        raise ValueError('CSV contains no samples')
    adc = np.array([[float(r['Pressure1']), float(r['Pressure2'])] for r in rows])
    if not np.isfinite(adc).all() or np.any((adc < 0) | (adc > 4095)):
        raise ValueError('Pressure columns must contain finite 12-bit ADC counts (0..4095)')
    if np.any(adc != np.floor(adc)):
        raise ValueError('ADC counts must be integers')
    index = np.array([int(r['SampleIndex']) for r in rows], dtype=np.int64) if has_index else np.arange(len(rows))
    if np.any(index < 0) or np.any(np.diff(index) <= 0):
        raise ValueError('SampleIndex must be nonnegative and strictly increasing')
    return adc, index, [r['Timestamp'] for r in rows], has_index


def process(adc, index, fs=1000.0, vref=3.3, cutoff=50.0, calibration=None):
    """Use nominal sample time, not USB receipt/dump-write timestamps."""
    if not np.isfinite(fs) or fs <= 0 or not np.isfinite(vref) or vref <= 0:
        raise ValueError('Sample rate and reference voltage must be positive and finite')
    voltage = adc * (vref / 4095.0)
    pressure = voltage.copy()
    if calibration is not None:
        for channel, key in enumerate(('P1', 'P2')):
            slope = float(calibration[key]['m'])
            offset = float(calibration[key]['b'])
            if not np.isfinite(slope) or slope == 0 or not np.isfinite(offset):
                raise ValueError('Calibration requires finite nonzero m and finite b for each channel')
            pressure[:, channel] = (voltage[:, channel] - offset) / slope
    signals = np.column_stack((pressure, pressure[:, 0] - pressure[:, 1]))
    filtered = signals.copy()
    if cutoff is not None:
        if not np.isfinite(cutoff) or not 0 < cutoff < fs / 2:
            raise ValueError('Low-pass cutoff must be between zero and half the sample rate')
        if np.any(np.diff(index) != 1):
            raise ValueError('Cannot filter across missing sample indices; use --no-filter')
        sos = butter(8, cutoff, fs=fs, output='sos')
        try:
            filtered = sosfiltfilt(sos, signals, axis=0)
        except ValueError as exc:
            raise ValueError('Record is too short for the filter; use --no-filter') from exc
    return dict(t=(index-index[0])/fs, adc1=adc[:, 0], adc2=adc[:, 1],
                v1=voltage[:, 0], v2=voltage[:, 1], p1=signals[:, 0],
                p2=signals[:, 1], dp=signals[:, 2], p1_f=filtered[:, 0],
                p2_f=filtered[:, 1], dp_f=filtered[:, 2], sample_index=index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--fs', type=float, default=1000, help='Nominal ADC rate in Hz; match firmware')
    parser.add_argument('--vref', type=float, default=3.3)
    parser.add_argument('--lowpass', type=float, default=50)
    parser.add_argument('--no-filter', action='store_true')
    parser.add_argument('--calibration', type=Path, help='JSON with P1/P2: {m: volts/Pa, b: volts}')
    parser.add_argument('--outdir', type=Path, help='New directory; must not already exist')
    args = parser.parse_args()
    try:
        adc, index, timestamps, has_index = load_csv(args.csv)
        calibration = json.loads(args.calibration.read_text()) if args.calibration else None
        result = process(adc, index, args.fs, args.vref,
                         None if args.no_filter else args.lowpass, calibration)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))

    outdir = args.outdir or args.csv.parent / 'Results' / (args.csv.stem + '_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    outdir.mkdir(parents=True, exist_ok=False)
    unit = 'Pa' if calibration is not None else 'V'
    metadata = dict(source=str(args.csv.resolve()), samples=len(adc), fs_nominal=args.fs,
                    vref=args.vref, adc_bits=12, unit=unit, calibration=calibration,
                    lowpass_hz=None if args.no_filter else args.lowpass,
                    filter_order=None if args.no_filter else 8,
                    time_basis='SampleIndex/fs (nominal)' if has_index else 'received row number/fs (nominal)',
                    has_sample_index=has_index, missing_indices=int(np.sum(np.diff(index)-1)),
                    timestamp_unique_count=len(set(timestamps)),
                    caveat='Host timestamps are not ADC acquisition times. Realtime losses cannot be detected without firmware sample counters.')
    (outdir / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    np.savez_compressed(outdir / 'processed.npz', **result, timestamp=np.array(timestamps), fs=args.fs)
    savemat(outdir / 'processed.mat', {**result, 'fs': args.fs, 'Vref': args.vref, 'adcBits': 12})
    with (outdir / 'processed.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Timestamp', *result.keys()])
        writer.writerows(zip(timestamps, *result.values()))

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, constrained_layout=True)
    for axis, key, label in zip(axes, ('p1', 'p2', 'dp'), ('P1', 'P2', 'P1 - P2')):
        axis.plot(result['t'], result[key], linewidth=0.7, alpha=0.6, label='Raw')
        if not args.no_filter:
            axis.plot(result['t'], result[key+'_f'], linewidth=1, label=f'{args.lowpass:g} Hz low-pass')
        axis.set_ylabel(f'{label} ({unit})')
        axis.grid(alpha=0.3)
        axis.legend(loc='upper right')
    axes[-1].set_xlabel('Nominal time (s); ADC acquisition timestamps unavailable')
    fig.suptitle(args.csv.name)
    fig.savefig(outdir / 'pressure.png', dpi=200)
    plt.close(fig)
    print(f'Processed {len(adc)} samples; units={unit}; nominal fs={args.fs:g} Hz')
    print(metadata['caveat'])
    print(f'Saved CSV, NPZ, MAT, metadata, and plot to {outdir.resolve()}')


if __name__ == '__main__':
    main()
