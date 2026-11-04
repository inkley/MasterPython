"""Quick-look analysis of the independent P1 and P2 differential-pressure channels."""

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

from measured_time import load_measured_time, break_plot

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


def process(adc, index, fs=1000.0, vref=3.3, cutoff=150.0, calibration=None):
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
    # Each channel already measures a pressure difference across its own ports.
    signals = pressure
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
                p2=signals[:, 1], p1_f=filtered[:, 0],
                p2_f=filtered[:, 1], sample_index=index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--fs', type=float, default=1000, help='Nominal ADC rate in Hz; match firmware')
    parser.add_argument('--vref', type=float, default=3.3)
    parser.add_argument('--lowpass', type=float, default=150, help='Low-pass cutoff in Hz (default: 150)')
    parser.add_argument('--no-filter', action='store_true')
    parser.add_argument('--calibration', type=Path, help='JSON with P1/P2: {m: volts/Pa, b: volts}')
    parser.add_argument('--outdir', type=Path, help='New directory; must not already exist')
    args = parser.parse_args()
    try:
        adc, index, timestamps, has_index = load_csv(args.csv)
        measured = load_measured_time(args.csv,index)
        calibration = json.loads(args.calibration.read_text()) if args.calibration else None
        effective_cutoff=None if args.no_filter else args.lowpass
        filter_note=None
        if measured is not None:
            if args.fs!=1000: raise ValueError('Measured profile is nominal 1000 Hz; do not relabel with --fs')
            if not measured['uniform'] or measured['gap'].any() or any(measured['quality']):
                effective_cutoff=None
                filter_note='Filtering disabled: measured times are irregular, gapped or quality-degraded; no implicit resampling.'
        result = process(adc,index,args.fs,args.vref,effective_cutoff,calibration)
        if measured is not None:
            result['t']=measured['t']
            result['trigger_ticks']=np.array(measured['ticks'],dtype=np.uint64)
            result['attempt_index']=np.array(measured['attempts'],dtype=np.uint32)
            result['gap_before']=measured['gap']
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))

    outdir = args.outdir or args.csv.parent / 'Results' / (args.csv.stem + '_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    outdir.mkdir(parents=True, exist_ok=False)
    unit = 'Pa' if calibration is not None else 'V'
    metadata = dict(source=str(args.csv.resolve()), samples=len(adc), fs_nominal=args.fs,
                    vref=args.vref, adc_bits=12, unit=unit, calibration=calibration,
                    lowpass_hz=effective_cutoff,
                    filter_order=None if effective_cutoff is None else 8,
                    time_basis='SampleIndex/fs (nominal)' if has_index else 'received row number/fs (nominal)',
                    has_sample_index=has_index, missing_indices=int(np.sum(np.diff(index)-1)),
                    timestamp_unique_count=len(set(timestamps)),
                    caveat='Host timestamps are not ADC acquisition times. Realtime losses cannot be detected without firmware sample counters.')
    if measured is not None:
        metadata.update(time_basis='RAW_TRIGGER_TICKS relative to first valid trigger',
                        recording_id=measured['recording_id'],time_domain_id=measured['time_domain_id'],
                        clock_hz=measured['clock_hz'],gap_boundaries=int(measured['gap'].sum()),
                        event_details_available=measured['event_details_available'],
                        annotated_events=len(measured['event_times']),
                        utc=None,utc_error_bound_ns=None,quality_flags=measured['quality'],
                        filter_note=filter_note,
                        caveat='Measured pre-software-trigger proxy, MCU-clock-relative; ADC aperture and UTC are unknown.')
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
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, constrained_layout=True)
    for axis, key, label in zip(axes, ('p1', 'p2'), ('P1', 'P2')):
        t,y=break_plot(result['t'],result[key],measured['gap']) if measured is not None else (result['t'],result[key])
        axis.plot(t,y,linewidth=0.7,alpha=0.6,label='Raw')
        if measured is not None:
            gaps=np.flatnonzero(measured['gap'])
            if len(gaps):
                endpoints=np.unique(np.r_[gaps,np.maximum(0,gaps-1)])
                axis.scatter(result['t'][endpoints],result[key][endpoints],s=8,color='C0',alpha=0.7)
            boundaries=sorted(set(result['t'][measured['gap']].tolist()+measured['event_times']))
            for j,boundary in enumerate(boundaries):
                axis.axvline(boundary,color='crimson',alpha=0.4,linewidth=0.7,linestyle='--',label='Timing/gap event' if j==0 else None)
        if effective_cutoff is not None:
            axis.plot(result['t'], result[key+'_f'], linewidth=1, label=f'{args.lowpass:g} Hz low-pass')
        axis.set_ylabel(f'{label} ({unit})')
        axis.grid(alpha=0.3)
        axis.legend(loc='upper right')
    axes[-1].set_xlabel('Measured trigger elapsed time (s); UTC unavailable' if measured is not None else 'Nominal time (s); ADC acquisition timestamps unavailable')
    prefix='OFFLINE fixture: ' if measured is not None and measured['origin']=='OFFLINE' else ''
    if measured is not None and measured['origin']=='MCU_BENCH_RAM':prefix='BENCH controlled injection: '
    suffix=' — timing quality degraded' if measured is not None and any(measured['quality']) else ''
    fig.suptitle(prefix+args.csv.name+suffix)
    fig.savefig(outdir / 'pressure.png', dpi=200)
    plt.close(fig)
    print(f'Processed {len(adc)} samples; units={unit}; nominal fs={args.fs:g} Hz')
    print(metadata['caveat'])
    if filter_note: print(filter_note)
    print(f'Saved CSV, NPZ, MAT, metadata, and plot to {outdir.resolve()}')


if __name__ == '__main__':
    main()
