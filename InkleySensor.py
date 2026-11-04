"""
Author: Tyler Inkley

Inkley_SensorCommander (Python CLI)
- Command-line interface for interacting with the Inkley/Tiva pressure sensor module over CAN (SLCAN/CANable).
- Supports:
    * Query firmware versiclon (ACK via PC_RESP_ID)
    * Start/stop real-time streaming
    * Dump buffered samples from the module
    * Request current readings (command-based)
    * Scan and select serial/CAN interface ports
    * Set logging output directory + CSV filename
- Logging:
    * Writes a CSV with columns: Timestamp, Pressure1, Pressure2
    * Supports high-rate “packed” broadcast frames on CAN ID 0x7DF (frame_type=0x05, sensor_id=0x12)
      where Pressure1/Pressure2 are 12-bit ADC counts packed into bytes [2..5].
    * Flushes periodically to reduce data loss risk.
- Protocol notes:
    * Commands are sent TO the module at CAN ID 0x107.
    * The module returns ACK/response frames to PC_RESP_ID (default 0x108), included in the command payload.
- Typical usage:
    1) scan_ports   (or set_channel COMx)
    2) set_outdir   <path>     (optional)
    3) set_filename <file.csv> (optional)
    4) start        (real-time logging)  /  stop
    5) version      (query firmware build/version)

Dependencies:
- python-can
- pyserial

Last updated: 2026-02-16
"""

import can
import csv
import datetime
import struct
import cmd
import threading
import platform
import serial.tools.list_ports
import os
import time
import uuid
import json
import zlib
from measured_export import download_v2, export_v2
from timing_protocol import WORD_COUNT, collect_words, decode_snapshot
from flash_protocol import manifest_info, validate_recording, validate_block
from flash_lifecycle import verified_file
from pathlib import Path

# Global configuration
CAN_CHANNEL = 'COM5'

# NEW: the CAN ID PC/listener will receive ACK responses on
PC_RESP_ID = 0x108

# Must match firmware SYSTICK_TIMING. These are estimated host timestamps,
# not acquisition timestamps; USB buffering can still cause overlaps/jitter.
SAMPLE_PERIOD = datetime.timedelta(milliseconds=1)


def packed_sample_timestamps(received_at):
    """Anchor sample B to host receipt and sample A one ADC tick earlier."""
    return (received_at - SAMPLE_PERIOD, received_at)

def detect_os():
    """Detect the current operating system"""
    system = platform.system().lower()
    if system == 'windows':
        return 'Windows'
    elif system == 'darwin':
        return 'macOS'
    elif system == 'linux':
        return 'Linux'
    else:
        return f'Unknown ({system})'

def scan_can_ports():
    """Scan for available CAN interface serial ports (CANdo/CANable devices)"""
    ports = []
    available_ports = serial.tools.list_ports.comports()
    
    # Common identifiers for CAN interfaces
    can_identifiers = [
        'canable',
        'cando', 
        'slcan',
        'can',
        'cantact',
        'usb2can',
        'peak',
        'kvaser'
    ]
    
    for port in available_ports:
        port_info = {
            'device': port.device,
            'description': port.description or '',
            'manufacturer': port.manufacturer or '',
            'vid_pid': f"{port.vid:04X}:{port.pid:04X}" if port.vid and port.pid else '',
            'serial_number': port.serial_number or '',
            'is_can_device': False
        }
        
        # Check if this might be a CAN device based on description, manufacturer, or VID/PID
        search_text = f"{port_info['description']} {port_info['manufacturer']} {port_info['serial_number']}".lower()
        
        for identifier in can_identifiers:
            if identifier in search_text:
                port_info['is_can_device'] = True
                break
        
        # Also check for common CAN device VID/PIDs
        can_vid_pids = [
            '1D50:606F',  # CANable
            '16C0:27DD',  # CANtact
            '0483:5740',  # STM32 (common for CAN devices)
        ]
        
        if port_info['vid_pid'] in can_vid_pids:
            port_info['is_can_device'] = True
            
        ports.append(port_info)
    
    return ports

def select_can_port():
    """Interactive port selection for CAN interface"""
    global CAN_CHANNEL
    
    print(f"\nDetected OS: {detect_os()}")
    print("Scanning for available serial ports...")
    
    ports = scan_can_ports()
    
    if not ports:
        print("No serial ports found!")
        return None
    
    # Separate CAN devices from other ports
    can_ports = [p for p in ports if p['is_can_device']]
    other_ports = [p for p in ports if not p['is_can_device']]
    
    print("\n" + "="*80)
    print("AVAILABLE SERIAL PORTS")
    print("="*80)
    
    port_options = []
    option_num = 1
    
    if can_ports:
        print("\nLikely CAN Interface Devices:")
        print("-" * 40)
        for port in can_ports:
            print(f"  {option_num}. {port['device']}")
            print(f"     Description: {port['description']}")
            if port['manufacturer']:
                print(f"     Manufacturer: {port['manufacturer']}")
            if port['vid_pid'] != ':':
                print(f"     VID:PID: {port['vid_pid']}")
            if port['serial_number']:
                print(f"     Serial: {port['serial_number']}")
            print()
            port_options.append(port)
            option_num += 1
    
    if other_ports:
        print("Other Serial Ports:")
        print("-" * 40)
        for port in other_ports:
            print(f"  {option_num}. {port['device']}")
            print(f"     Description: {port['description']}")
            if port['manufacturer']:
                print(f"     Manufacturer: {port['manufacturer']}")
            if port['vid_pid'] != ':':
                print(f"     VID:PID: {port['vid_pid']}")
            print()
            port_options.append(port)
            option_num += 1
    
    print(f"  {option_num}. Enter custom port manually")
    print(f"  {option_num + 1}. Skip port selection (use default)")
    
    while True:
        try:
            choice = input(f"\nSelect a port (1-{option_num + 1}): ").strip()
            
            if not choice:
                continue
                
            choice_num = int(choice)
            
            if 1 <= choice_num <= len(port_options):
                selected_port = port_options[choice_num - 1]
                CAN_CHANNEL = selected_port['device']
                print(f"Selected port: {CAN_CHANNEL}")
                return CAN_CHANNEL
            elif choice_num == option_num:
                # Manual entry
                custom_port = input("Enter custom port (e.g., COM8, /dev/ttyUSB0): ").strip()
                if custom_port:
                    CAN_CHANNEL = custom_port
                    print(f"Using custom port: {CAN_CHANNEL}")
                    return CAN_CHANNEL
            elif choice_num == option_num + 1:
                # Skip selection
                print("Skipping port selection. You can set it later using 'set_channel' command.")
                return None
            else:
                print(f"Invalid choice. Please enter a number between 1 and {option_num + 1}")
                
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nPort selection cancelled.")
            return None

class CANBusCommander(cmd.Cmd):
    intro = """Inkley Sensor Command Line Interface. Type 'help' for commands.\n
Inkley Sensor CLI Menu:
  1 - Display version
  2 - Start real-time streaming
  3 - Stop streaming
  4 - Dump buffered sensor data
  5 - Show buffer status
  6 - Scan and select CAN ports
  7 - Show system information
  8 - Exit program

Additional commands:
  set_channel      - Set the COM port for the CANable interface
  scan_ports       - Scan for available CAN interface ports
  system_info      - Display OS and port information
  set_outdir       - Set output directory for CSV logging
  set_filename     - Set CSV filename for logging
  set_buffer_size  - Set the RAM buffer size (samples) used while streaming
  buffer_status    - Show firmware RAM buffer status
  dump_buffer      - Download buffered sample data and save to CSV
  read_flash       - Backward-compatible alias for dump_buffer
  measured_bench_gap - RAM-only 5 ms delay test using protected-record backup (.243+)
  measured_bench_fault - RAM-only ADC error/timeout or event-overflow test (.244+)
  measured_bench_discard - Discard only matching exported bench RAM (.243+)
  stack_status     - Read observed stack watermark (.243+)
  measured_init    - Assign/query boot timer domain (.242+)
  measured_capture - Capture 1..1024 timestamped pairs (.242+)
  dump_measured    - Verify/export frozen measured RAM without deleting it
  timing_reset     - Reset stopped timing diagnostics (.241+)
  timing_start     - Start idle or can test without changing retained recordings
  timing_stop      - Stop diagnostic acquisition
  timing_status    - Save CRC-verified timing JSON report
  ack_flash        - Verify/flush saved binary, ACK transfer; retain local recording
  clear_flash      - Explicitly delete matching ACKed recording using saved binary
  flash_recovery   - Read-only partition recovery classification (.239+)
  flash_scratch    - Bench scratch-only fault fixtures (.239+; help flash_scratch)
  flash_capture    - Bounded RAM capture (e.g. flash_capture 1000)
  flash_stop       - Stop bounded capture early
  flash_status     - Read persistence state
  persist_buffer   - Save stopped bounded capture to blank flash
  verify_flash     - Verify actual flash recording
  dump_flash       - Download/verify actual flash, preserving it
  clear            - Clear the terminal window
  home             - Show this menu
"""
    prompt = "> "
    
    # Define command numbers for quick access
    COMMAND_MAP = {
        '1': 'version',
        '2': 'start',
        '3': 'stop',
        '4': 'dump_buffer',
        '5': 'buffer_status',
        '6': 'scan_ports',
        '7': 'system_info',
        '8': 'quit'
    }

    def __init__(self):
        super().__init__()
        self.bus = None
        self.streaming = False
        self.stream_thread = None

        # --- Output file settings ---
        self.output_dir = Path.cwd() / "Data"     # default folder: ./Data
        self.csv_file = "Inkley_sensor_data.csv" # default filename (can be overridden)
        
        # Print the current CAN channel at startup
        if CAN_CHANNEL:
            print(f"Using CAN channel: {CAN_CHANNEL}\n")
        else:
            print("No CAN channel configured. Use 'scan_ports' (option 6) or 'set_channel' to configure a port.")

        # Latest-known values + timestamps for deterministic logging
        self.sensor_data = {
            'Pressure1': None,
            'Pressure2': None,
        }
        self.sensor_time = {
            'Pressure1': None,
            'Pressure2': None,
        }

        # Locks / synchronization for CAN bus access + response handling
        self.bus_lock = threading.Lock()          # Protects access to self.bus (send/recv/shutdown)
        self.data_lock = threading.Lock()         # Protects sensor_data/sensor_time

        # Response handling (used when streaming is active)
        self.expected_response_cmd = None
        self.response_data = None
        self.response_event = threading.Event()

        # Define CAN ID and sensor IDs
        self.CAN_ID = 0x107  # Updated to new sensor module CAN ID
        self.SENSOR_IDS = {
            0x01: 'Pressure1',
            0x02: 'Pressure2'#,
            #0x03: 'Temperature1',
            #0x04: 'Temperature2'
        }
        # Command IDs for sending to the sensor module
        self.CMD_VERSION = 0x01
        self.CMD_START_STREAM = 0x02
        self.CMD_STREAM_BUFFER = 0x03
        self.CMD_STOP_STREAM = 0x04
        self.CMD_GET_READINGS = 0x05
        self.CMD_BUFFER_STATUS = 0x05
        self.CMD_STREAM_BUFFER_SET = 0x06
        self.CMD_BUFFERED_SAMPLE_DATA = 0x07
        # Historical alias retained for older scripts/workflows.
        self.CMD_READ_FLASH = self.CMD_BUFFERED_SAMPLE_DATA
        
        self.version = "1.0.0"
        
    def initialize_can_bus(self):
        """Initialize the CAN bus if not already initialized"""
        with self.bus_lock:
            if self.bus is not None:
                return True

            if CAN_CHANNEL is None:
                print("No CAN channel configured. Use 'scan_ports' or 'set_channel' to configure a port.")
                return False
            try:
                # Use the global CAN_CHANNEL variable
                # NOTE: Use 1 Mbps for high-rate sampling (matches the MCU firmware)
                self.bus = can.interface.Bus(interface='slcan', channel=CAN_CHANNEL, bitrate=1000000)
                print(f"CAN bus initialized successfully on {CAN_CHANNEL}")
                return True
            except Exception as e:
                print(f"Error initializing CAN bus on {CAN_CHANNEL}: {e}")
                return False
        
    def send_command(self, command_id, value_u32=None):
        """Send a command to the sensor module via CAN bus.
        Payload format (matches Tiva main.c):
          [0]=cmd, [1]=resp_id_hi, [2]=resp_id_lo, [3..6]=u32 value, [7]=0
        """
        if not self.initialize_can_bus():
            return False

        resp_hi = (PC_RESP_ID >> 8) & 0xFF
        resp_lo = (PC_RESP_ID >> 0) & 0xFF

        if value_u32 is None:
            b3 = b4 = b5 = b6 = 0
        else:
            value_u32 = int(value_u32) & 0xFFFFFFFF
            b3 = (value_u32 >> 24) & 0xFF
            b4 = (value_u32 >> 16) & 0xFF
            b5 = (value_u32 >>  8) & 0xFF
            b6 = (value_u32 >>  0) & 0xFF

        message_data = [command_id, resp_hi, resp_lo, b3, b4, b5, b6, 0x00]

        try:
            msg = can.Message(
                arbitration_id=self.CAN_ID,   # send TO the module (0x107)
                data=message_data,
                is_extended_id=False
            )
            with self.bus_lock:
                self.bus.send(msg)
            return True
        except Exception as e:
            print(f"Error sending command {hex(command_id)}: {e}")
            return False

    def _recv_frame(self, timeout):
        """Receive with the caller holding bus_lock; discard malformed SLCAN input."""
        try:
            return self.bus.recv(timeout=timeout)
        except (ValueError, IndexError) as exc:
            # python-can's SLCAN parser can reject startup/partial serial lines.
            # Keep request deadlines intact and make potential data loss visible.
            print(f"Warning: discarded malformed CAN input (possible data loss): {exc}")
            return None

    def _drain_pending_can_messages(self, max_messages=100):
        """Discard already-queued CAN frames before starting a request/response flow."""
        if self.bus is None:
            return 0

        drained = 0
        with self.bus_lock:
            while drained < max_messages:
                msg = self._recv_frame(timeout=0)
                if msg is None:
                    break
                drained += 1

        return drained

    def do_set_outdir(self, arg):
        """Set output directory (e.g., set_outdir C:\\data\\run1  OR  set_outdir ./data/run1)"""
        if not arg.strip():
            print(f"Current output directory: {self.output_dir.resolve()}")
            return
        self.output_dir = Path(arg.strip()).expanduser()
        print(f"Output directory set to: {self.output_dir.resolve()}")

    def do_set_filename(self, arg):
        """Set output CSV filename (e.g., set_filename test01.csv)"""
        name = arg.strip()
        if not name:
            print(f"Current filename: {self.csv_file}")
            return
        if not name.lower().endswith(".csv"):
            name += ".csv"
        self.csv_file = name
        print(f"Filename set to: {self.csv_file}")

    def do_set_output(self, arg):
        """Set both directory and filename.
    Usage: set_output <dir> <filename>
    Example: set_output C:\\data\\run1 trialA.csv
    Example: set_output ./data/run1 trialA.csv
    """
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: set_output <dir> <filename>")
            return
        outdir = parts[0]
        filename = " ".join(parts[1:])  # allow spaces if you really want them
        self.output_dir = Path(outdir).expanduser()
        if not filename.lower().endswith(".csv"):
            filename += ".csv"
        self.csv_file = filename
        print(f"Output set to: {(self.output_dir / self.csv_file).resolve()}")

    def _make_output_path(self) -> Path:
        """Return full output path; ensure directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / self.csv_file

    def stream_data(self):
        # Initialize CAN bus interface for CANable
        try:
            if not self.initialize_can_bus():
                print("Failed to initialize CAN bus")
                return
            
            out_path = self._make_output_path()
            print(f"Logging to: {out_path.resolve()}")
            with open(out_path, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(['Timestamp', 'Pressure1', 'Pressure2'])
                sample_counter = 0
                last_write_time = datetime.datetime.now()
                write_period_s = 1.0
                stale_after_s = 2.0

                # Buffer rows in memory and flush in batches to avoid slow per-row I/O.
                buffered_rows = []
                flush_every = 2000

                frames_received = 0
                no_msg_ticks = 0

                while self.streaming:
                    # Wake up at least every 0.1s even if no CAN messages arrive
                    with self.bus_lock:
                        msg = self._recv_frame(timeout=0.1)
                    current_time = datetime.datetime.now()

                    handled = False

                    if msg is None:
                        no_msg_ticks += 1
                        # Report if we haven't seen any CAN frames for 5 seconds
                        if no_msg_ticks == 50:
                            print("No CAN frames received for 5 seconds (is the module still streaming?)")
                        continue

                    no_msg_ticks = 0
                    frames_received += 1

                    # Handle ACK/response frames coming back to the PC.
                    if msg.arbitration_id == PC_RESP_ID and len(msg.data) == 8:
                        cmd_id = msg.data[3]
                        if cmd_id == self.CMD_VERSION:
                            major, minor, patch, build = msg.data[4], msg.data[5], msg.data[6], msg.data[7]
                            self.version = f"{major}.{minor}.{patch}.{build}"
                            print(f"Received firmware version: {self.version}")

                            if self.expected_response_cmd == cmd_id:
                                self.response_data = (major, minor, patch, build)
                                self.response_event.set()
                        else:
                            val = (msg.data[4] << 24) | (msg.data[5] << 16) | (msg.data[6] << 8) | msg.data[7]
                            print(f"ACK cmd={hex(cmd_id)} value={val}")
                            if self.expected_response_cmd == cmd_id:
                                self.response_data = val
                                self.response_event.set()
                        continue

                    # --- Special-case: broadcast realtime frames from Tiva (ID 0x7DF) ---
                    if msg.arbitration_id == 0x7DF and len(msg.data) == 8:
                        frame_type = msg.data[0]
                        sensor_id  = msg.data[1]


                        if frame_type in (0x05, 0x06):

                            # -------- NEW PACKED MODE --------
                            if sensor_id == 0x12:   # packed P1 + P2
                                if frame_type == 0x05:
                                    # Legacy 1-sample-per-frame mode
                                    p1 = (msg.data[2] << 8) | msg.data[3]
                                    p2 = (msg.data[4] << 8) | msg.data[5]

                                    with self.data_lock:
                                        self.sensor_data['Pressure1'] = p1
                                        self.sensor_time['Pressure1'] = current_time
                                        self.sensor_data['Pressure2'] = p2
                                        self.sensor_time['Pressure2'] = current_time

                                    # Buffer each sample and flush periodically to reduce I/O overhead.
                                    buffered_rows.append([current_time.isoformat(timespec="milliseconds"), p1, p2])
                                    sample_counter += 1   # increment

                                else:
                                    # New 2-samples-per-frame mode (reduced bus load)
                                    # Frame payload (bytes 2..7) holds two 12-bit P1/P2 samples.
                                    # Layout (each sample = p1 (12b) + p2 (12b)):
                                    #   [2..4] = sample A
                                    #   [5..7] = sample B
                                    p1_a = (msg.data[2] << 4) | (msg.data[3] >> 4)
                                    p2_a = ((msg.data[3] & 0x0F) << 8) | msg.data[4]
                                    p1_b = (msg.data[5] << 4) | (msg.data[6] >> 4)
                                    p2_b = ((msg.data[6] & 0x0F) << 8) | msg.data[7]

                                    with self.data_lock:
                                        # Update latest values for each pressure channel
                                        self.sensor_data['Pressure1'] = p1_b
                                        self.sensor_time['Pressure1'] = current_time
                                        self.sensor_data['Pressure2'] = p2_b
                                        self.sensor_time['Pressure2'] = current_time

                                    time_a, time_b = packed_sample_timestamps(current_time)
                                    buffered_rows.append([time_a.isoformat(timespec="microseconds"), p1_a, p2_a])
                                    buffered_rows.append([time_b.isoformat(timespec="microseconds"), p1_b, p2_b])
                                    sample_counter += 2

                                # Flush every flush_every samples (reduce per-sample I/O overhead)
                                if sample_counter % flush_every == 0:
                                    writer.writerows(buffered_rows)
                                    file.flush()
                                    buffered_rows.clear()

                                if sample_counter % 1000 == 0:
                                    print(f"Logged {sample_counter} samples")

                            # -------- OLD SINGLE SENSOR MODE (keep for safety) --------
                            elif sensor_id in self.SENSOR_IDS:
                                value = struct.unpack('>I', bytes(msg.data[4:8]))[0]
                                name = self.SENSOR_IDS[sensor_id]

                                with self.data_lock:
                                    self.sensor_data[name] = value
                                    self.sensor_time[name] = current_time

                                print(f"[BC] {name}: {value}")

                        handled = True

                # Flush any remaining buffered samples before closing the file
                if buffered_rows:
                    writer.writerows(buffered_rows)
                    file.flush()
                    buffered_rows.clear()

                # Streaming loop exited (self.streaming set to False or loop ended)
                print(f"Streaming loop exited after logging {sample_counter} samples")

        except Exception as e:
            print(f"Streaming error: {e}")
        finally:
            if self.bus:
                self.bus.shutdown()
                self.bus = None
            print(f"Sensor data saved to {out_path.resolve() if 'out_path' in locals() else self.csv_file}")

    def do_version(self, arg):
        """Display the version of the sensor module firmware"""
        # Prepare for a response (the stream thread will signal this event)
        self.response_event.clear()
        self.expected_response_cmd = self.CMD_VERSION
        self.response_data = None

        if not self.send_command(self.CMD_VERSION):
            print("Failed to send version request command")
            print(f"Local version: {self.version}")
            self.expected_response_cmd = None
            return

        print("Version request sent to sensor module. Waiting for response...")

        if self.streaming:
            # When streaming, the stream thread is responsible for consuming CAN frames
            if self.response_event.wait(timeout=5):
                major, minor, patch, build = self.response_data
                self.version = f"{major}.{minor}.{patch}.{build}"
                print(f"Sensor module firmware version: {self.version}")
            else:
                print("No response received from sensor module. Using local version.")
                print(f"Local version: {self.version}")
        else:
            # When not streaming, read directly from the bus (protected by lock)
            try:
                if not self.initialize_can_bus():
                    print("Failed to initialize CAN bus")
                    return

                start_time = datetime.datetime.now()
                timeout = 5  # seconds

                while (datetime.datetime.now() - start_time).total_seconds() < timeout:
                    with self.bus_lock:
                        msg = self._recv_frame(1)

                    if msg and msg.arbitration_id == PC_RESP_ID and len(msg.data) == 8:
                        cmd_id = msg.data[3]
                        if cmd_id == self.CMD_VERSION:
                            major, minor, patch, build = msg.data[4], msg.data[5], msg.data[6], msg.data[7]
                            self.version = f"{major}.{minor}.{patch}.{build}"
                            print(f"Sensor module firmware version: {self.version}")
                            return

                print("No response received from sensor module. Using local version.")
                print(f"Local version: {self.version}")

            except Exception as e:
                print(f"Error receiving version response: {e}")
                print(f"Local version: {self.version}")

        self.expected_response_cmd = None

    def do_start(self, arg):
        """Start legacy realtime streaming after module acknowledgement."""
        if self.streaming:
            print("Streaming is already active")
            return
        result = self._recv_u32_response(self.CMD_START_STREAM)
        if result != 1:
            print(f"Start rejected or outcome unknown: {result}. Check flash_status/version.")
            return
        self.streaming = True
        self.stream_thread = threading.Thread(target=self.stream_data, daemon=True)
        self.stream_thread.start()
        print("Started real-time streaming")

    def do_stop(self, arg):
        """Stop streaming"""
        if self.streaming:
            if self.send_command(self.CMD_STOP_STREAM):
                self.streaming = False
                if self.stream_thread:
                    self.stream_thread.join()
                print("Stopped real-time streaming")
            else:
                print("Failed to send stop streaming command")
        else:
            print("Streaming is not active")

    def do_quit(self, arg):
        """Exit the command line interface"""
        if getattr(self, "_timing_active", False):
            self.do_timing_stop("")
        if self.streaming:
            self.send_command(self.CMD_STOP_STREAM)
            self.streaming = False
            if self.stream_thread:
                self.stream_thread.join()
        if self.bus:
            self.bus.shutdown()
            self.bus = None
        print("Exiting Sensor Commander")
        return True

    def do_exit(self, arg):
        """Alias for quit command"""
        return self.do_quit(arg)

    def do_clear(self, arg):
        """Clear the terminal window"""
        command = "cls" if os.name == "nt" else "clear"
        os.system(command)
        print()

    def do_home(self, arg):
        """Display the Inkley Sensor CLI menu"""
        print(self.intro)
        
    def do_set_buffer_size(self, arg):
        """Set the RAM buffer size used while streaming (command 6)."""
        try:
            size = int(arg.strip())
        except Exception:
            print("Usage: set_buffer_size <samples> (e.g., set_buffer_size 8192)")
            return

        if size <= 0:
            print("Buffer size must be positive")
            return

        value = self._recv_u32_response(self.CMD_STREAM_BUFFER_SET, value_u32=size)
        if value is None:
            print("Buffer size response unavailable; outcome unknown")
        elif value & 0x80000000:
            print("Buffer size change rejected; retained recording unchanged")
        else:
            print(f"Firmware RAM buffer capacity set to {value}")

    def _recv_u32_response(self, command_id, timeout=5, value_u32=None):
        """Send a command and return its uint32 response value."""
        self.response_event.clear()
        self.expected_response_cmd = command_id
        self.response_data = None

        if not self.send_command(command_id, value_u32):
            self.expected_response_cmd = None
            return None

        if self.streaming:
            if self.response_event.wait(timeout=timeout):
                value = self.response_data
                self.expected_response_cmd = None
                return value

            self.expected_response_cmd = None
            return None

        start_time = datetime.datetime.now()
        while (datetime.datetime.now() - start_time).total_seconds() < timeout:
            with self.bus_lock:
                msg = self._recv_frame(1)

            if msg and msg.arbitration_id == PC_RESP_ID and len(msg.data) == 8:
                cmd_id = msg.data[3]
                if cmd_id == command_id:
                    self.expected_response_cmd = None
                    return (msg.data[4] << 24) | (msg.data[5] << 16) | (msg.data[6] << 8) | msg.data[7]

        self.expected_response_cmd = None
        return None

    def _timing_ready(self):
        if not self.initialize_can_bus(): return False
        if not self.streaming: self._drain_pending_can_messages()
        if self._recv_u32_response(0x0f) != 0x49500104:
            print("Timing diagnostics require firmware 0.0.3.241. No test started.")
            return False
        return True

    def do_timing_reset(self, arg):
        """Reset volatile timing counters; acquisition must be stopped."""
        if self._timing_ready() and self._flash_result(self._recv_u32_response(0x2b)):
            print("Timing counters reset. No stored recording changed.")

    def do_timing_start(self, arg):
        """timing_start idle|can: acquire without RAM/flash writes; can also logs received samples."""
        mode = {'idle': 1, 'can': 2}.get(arg.strip().lower())
        if mode is None:
            print("Usage: timing_start idle|can")
            return
        if self.streaming:
            print("Stop streaming first.")
            return
        if not self._timing_ready(): return
        result = self._recv_u32_response(0x2f, value_u32=mode)
        if not self._flash_result(result): return
        if result != mode:
            print("Unexpected timing mode response; use timing_stop.")
            return
        self._timing_active = True
        if mode == 2:
            self.csv_file = 'timing_can_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv'
            self.streaming = True
            self.stream_thread = threading.Thread(target=self.stream_data, daemon=True)
            self.stream_thread.start()
        print("Diagnostic acquisition started; retained RAM/flash unchanged. Run ~10 s, then timing_stop.")

    def do_timing_stop(self, arg):
        """Stop diagnostic acquisition, keeping diagnostics and stored recordings."""
        if not self._timing_ready(): return
        result = self._recv_u32_response(0x2f, value_u32=0)
        if not self._flash_result(result): return
        if result != 0:
            print("Unexpected stop response; outcome unknown.")
            return
        self._timing_active = False
        self.streaming = False
        if self.stream_thread: self.stream_thread.join()
        print("Diagnostic acquisition stopped. Use timing_status <label>.")

    def do_timing_status(self, arg):
        """timing_status [label]: retrieve ordered CRC-checked snapshot and save JSON."""
        if self.streaming:
            print("Use timing_stop before retrieving diagnostics.")
            return
        if not self._timing_ready(): return
        count = self._recv_u32_response(0x2a)
        if count != WORD_COUNT:
            print(f"Timing snapshot unavailable or unsupported: {count}")
            return
        frames = []
        deadline = time.monotonic() + 15
        try:
            while len(frames) < count and time.monotonic() < deadline:
                with self.bus_lock: msg = self._recv_frame(0.1)
                if msg and msg.arbitration_id == PC_RESP_ID and len(msg.data) == 8 and msg.data[3] == 0x2d:
                    frames.append((int.from_bytes(msg.data[1:3], 'big'), bytes(msg.data[4:8])))
            report = decode_snapshot(collect_words(frames, count))
            report['host_received_at'] = datetime.datetime.now().astimezone().isoformat()
            label = ''.join(c if c.isalnum() or c in '_-' else '_' for c in (arg.strip() or 'timing'))[:80]
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / (label + '_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
            path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            v = report['counters']; us = report['microseconds']
            print(f"CRC-verified timing report saved: {path.resolve()}")
            print(f"Pairs: attempts={v['attempts']}, complete={v['completed']}, timeouts={v['adc_timeouts']}, ADC errors={v['adc_errors']}")
            print(f"Pair rate={report['pair_rate_hz']} Hz; trigger interval min/max={us['min_interval_ticks']:.3f}/{us['max_interval_ticks']:.3f} us")
            print(f"Outside +/-10 us={v['interval_outside_10us']}; estimated missing slots={v['estimated_missing_slots']}")
            print(f"CAN: queue drops={v['tx_queue_drops']}, TX failures={v['tx_failures']}, RX overruns software/hardware={v['rx_software_overruns']}/{v['rx_hardware_overruns']}")
            print(f"Flash erase/program calls={v['erase_calls']}/{v['program_calls']}; max duration={us['erase_max_ticks']:.3f}/{us['program_max_ticks']:.3f} us")
            print(f"Last storage kind={v['storage_kind']}, duration={us['storage_ticks']:.3f} us, ADC attempts during it={v['storage_attempts']}, flash calls={v['storage_flash_calls']}")
            print("CPU-relative instrumentation; no UTC, aperture timing, or host delivery guarantee. Avoid CCS halts during measurements.")
        except (ValueError, OSError) as exc:
            print(f"Timing report rejected/not saved: {exc}")

    def _bench_ready(self):
        if not self._measured_ready():return False
        if self._recv_u32_response(0x30,value_u32=8)!=0x424e4301:
            print('Bench/stack capability requires .243; no test started.');return False
        return True

    def do_stack_status(self, arg):
        """Read boot-painted stack watermark while acquisition is stopped; not a worst-case proof."""
        if not self._bench_ready():return
        free=self._recv_u32_response(0x3e,value_u32=0x5354414b)
        if not self._flash_result(free):return
        if free>4032:print('Invalid stack report');return
        print(f'Stack reservation=4096 bytes; pattern-unused={free}; estimated touched/unknown={4096-free}.')
        print('Observed watermark only; unpainted/reserved frames and pattern collisions limit it. Not worst-case stack acceptance.')
        if free<512:print('Insufficient/unknown painted margin: stop further stress testing and review.')

    def _bench_stage(self, request, target):
        raw=request.bytes+target.bytes
        for i in range(8):
            if not self._flash_result(self._recv_u32_response(0x20+i,value_u32=int.from_bytes(raw[4*i:4*i+4],'big'))):return False
        return True

    def do_measured_bench_gap(self, arg):
        """measured_bench_gap <protected recording.bin>: fixed64-pair RAM test, 5ms SysTick delay, no flash writes."""
        try:evidence=verified_file(arg.strip().strip('"'))
        except (ValueError,OSError) as exc:print(f'No test started: {exc}');return
        if evidence['format_version']!=2 or evidence.get('bench_injection'):print('This bench profile requires a protected normal v2 recording.');return
        if not self._bench_ready():return
        self._measured_domain_id=None;self.do_measured_init('')
        if self._measured_domain_id is None:return
        recording=uuid.uuid4()
        if not self._bench_stage(recording,evidence['recording_id']):return
        result=self._recv_u32_response(0x39,value_u32=evidence['manifest_crc'])
        if self._flash_result(result) and result==64:
            print(f'BENCH RAM capture {recording}:64 pairs, fixed5 ms service delay after attempt16.')
            print('Protected flash retained. Wait1 s, then dump_measured bench_gap_01; persist_buffer is blocked for bench data.')

    def do_measured_bench_fault(self, arg):
        """measured_bench_fault adc_error|adc_timeout|event_overflow <protected recording.bin>: RAM-only controlled negative test (.244+)."""
        parts=arg.strip().split(maxsplit=1)
        profiles={'adc_error':0x3a,'adc_timeout':0x3b,'event_overflow':0x3c}
        if len(parts)!=2 or parts[0] not in profiles:
            print('Usage: measured_bench_fault adc_error|adc_timeout|event_overflow <protected recording.bin>');return
        profile,path=parts
        try:evidence=verified_file(path.strip().strip('"'))
        except (ValueError,OSError) as exc:print(f'No test started: {exc}');return
        if evidence['format_version']!=2 or evidence.get('bench_injection'):
            print('Requires a protected normal v2 recording.');return
        if not self._bench_ready():return
        if self._recv_u32_response(0x30,value_u32=9)!=0x424e4302:
            print('Controlled fault capability requires .244; no test started.');return
        self._measured_domain_id=None;self.do_measured_init('')
        if self._measured_domain_id is None:return
        recording=uuid.uuid4()
        if not self._bench_stage(recording,evidence['recording_id']):return
        result=self._recv_u32_response(profiles[profile],value_u32=evidence['manifest_crc'])
        if self._flash_result(result) and result==64:
            print(f'BENCH RAM {profile}: {recording}. Wait1 s, then dump_measured bench_{profile}.')
            print('Protected flash retained; persistence blocked. ADC fault profiles latch acquisition until MCU reset.')

    def do_measured_bench_discard(self, arg):
        """measured_bench_discard <bench recording.bin>: verify saved bench evidence, discard only matching frozen RAM; flash retained."""
        try:
            path=Path(arg.strip().strip('"'));evidence=verified_file(path)
            from flash_v2 import decode_recording
            r=decode_recording(path.read_bytes())
            if r['metadata']['schema']!=2 or r['metadata']['feature_bits'] not in (1,2,3,4):raise ValueError('Not a supported bench recording')
        except (ValueError,OSError) as exc:print(f'No discard sent: {exc}');return
        if not self._bench_ready():return
        if not self._bench_stage(uuid.uuid4(),evidence['recording_id']):return
        result=self._recv_u32_response(0x3d,value_u32=evidence['manifest_crc'])
        if self._flash_result(result) and result==0:print('Matching bench RAM discarded; protected flash reverified and retained.')

    def _measured_ready(self):
        if not self._flash_ready(): return False
        if self._recv_u32_response(0x30,value_u32=0)!=0x49500201:
            print("Measured capture unavailable; .242+ capability required. No capture started.")
            return False
        if self._recv_u32_response(0x30,value_u32=1)!=1024 or self._recv_u32_response(0x30,value_u32=2)!=32:
            print("Unsupported measured capacities")
            return False
        return True

    def _measured_domain(self):
        assigned=self._recv_u32_response(0x30,value_u32=3)
        if assigned==0: return None
        if assigned!=1: raise ValueError('Unknown timer-domain state')
        words=[self._recv_u32_response(0x30,value_u32=i) for i in range(4,8)]
        if any(w is None for w in words) or self._recv_u32_response(0x30,value_u32=3)!=1:
            raise ValueError('Timer domain changed or reply missing')
        identity=uuid.UUID(bytes=b''.join(w.to_bytes(4,'big') for w in words))
        if not identity.int: raise ValueError('Invalid timer domain')
        return identity

    def do_measured_init(self, arg):
        """Query assigned boot timer domain, or assign a fresh UUID without resetting its timer."""
        if not self._measured_ready(): return
        try:
            domain=self._measured_domain()
            if domain is None:
                domain=uuid.uuid4()
                for i in range(4):
                    word=int.from_bytes(domain.bytes[4*i:4*i+4],'big')
                    if self._recv_u32_response(0x31+i,value_u32=word)!=word:
                        raise ValueError('Domain staging failed; no capture started')
                if self._recv_u32_response(0x35,value_u32=zlib.crc32(domain.bytes))!=1:
                    raise ValueError('Domain commit rejected/unknown')
                if self._measured_domain()!=domain: raise ValueError('Domain readback mismatch')
            self._measured_domain_id=domain
            print(f"Timer domain: {domain}; raw MCU ticks, UTC unavailable. Reconnect retains this ID; MCU reset requires a new ID.")
        except ValueError as exc: print(f"Measured initialization failed: {exc}")

    def do_measured_capture(self, arg):
        """measured_capture <1..1024>: bounded timestamped RAM capture; never implicitly clears recordings."""
        try: count=int(arg.strip())
        except ValueError: count=0
        if not 1<=count<=1024:
            print("Usage: measured_capture <1..1024>");return
        self._measured_domain_id=None
        self.do_measured_init('')
        if self._measured_domain_id is None: return
        recording=uuid.uuid4()
        for i in range(4):
            if not self._flash_result(self._recv_u32_response(0x10+i,value_u32=int.from_bytes(recording.bytes[i*4:i*4+4],'big'))):return
        token=zlib.crc32(recording.bytes+self._measured_domain_id.bytes+count.to_bytes(4,'big'))
        if self._recv_u32_response(0x38,value_u32=token)!=token:
            print("Measured capture token rejected/unknown; no start sent.");return
        result=self._recv_u32_response(0x36,value_u32=count)
        if self._flash_result(result) and result==count:
            print(f"Measured capture accepted: {recording}, domain={self._measured_domain_id}, limit={count} pairs.")
            print("Auto-stops; then flash_status, dump_measured LABEL, persist_buffer. No UTC is synthesized.")

    def do_dump_measured(self, arg):
        """dump_measured [label]: export frozen measured RAM with raw ticks, events, metadata and verified reconstructed binary."""
        if not self._measured_ready(): return
        stem=arg.strip() or 'measured_ram'
        if Path(stem).name!=stem or stem in ('.','..'):
            print("Use a label without directories");return
        try:
            image=download_v2(lambda p:self._tagged_read_block(0x37,0x3b,p))
            directory=self.output_dir/(stem+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            meta=export_v2(image,directory,'MCU_RAM')
            print(f"Verified {meta['summary']['samples']} measured RAM pairs; saved to {directory.resolve()}")
            if meta.get('bench_injection'):
                print("BENCH RAM only; persistence is blocked. Keep exported evidence before discarding or rebooting. UTC unavailable.")
            else:
                print("RAM remains volatile. Persist before reboot. Raw trigger ticks are measured; UTC unavailable.")
        except (ValueError,OSError) as exc: print(f"Measured RAM dump rejected: {exc}; source retained.")

    def _flash_ready(self):
        if self.streaming:
            print("Stop legacy streaming first.")
            return False
        if not self.initialize_can_bus():
            return False
        self._drain_pending_can_messages()
        self._flash_capability = self._recv_u32_response(0x0f)
        if self._flash_capability not in (0x49500101, 0x49500102, 0x49500103, 0x49500104):
            print("Stage-one flash capability unavailable; firmware 0.0.3.238 or newer required.")
            return False
        return True

    def _flash_result(self, result):
        errors = {1: 'busy', 2: 'invalid state', 3: 'invalid capture size',
                  4: 'missing UUID', 5: 'storage is nonblank/protected',
                  6: 'flash operation failed', 7: 'readback/CRC verification failed', 8: 'stale or mismatched recording identity',
                  9: 'journal uncertain or exhausted; retained read-only', 10: 'matching durable ACK required before clear', 11: 'ADC fault latched; preserve diagnostics and reset MCU before another acquisition',
                  12: 'timer domain unassigned; run measured_init', 13: 'unsupported MCU clock configuration',14: 'stack watermark margin insufficient or unavailable; bench test blocked'}
        if result is None:
            print("No response: outcome UNKNOWN. Query flash_status; do not retry destructively.")
            return False
        if result & 0x80000000:
            print(f"Module rejected/failed: {errors.get(result & 0x7fffffff, hex(result))}")
            return False
        return True

    def _recovery_ready(self):
        if not self._flash_ready(): return False
        if self._flash_capability not in (0x49500102, 0x49500103, 0x49500104):
            print("Recovery/scratch capability requires firmware 0.0.3.239. No write sent.")
            return False
        return True

    def do_flash_recovery(self, arg):
        """Read-only actual partition classification, including unreferenced blocks."""
        if not self._recovery_ready(): return
        result=self._recv_u32_response(0x1b, timeout=15)
        if not self._flash_result(result): return
        states={0:'EMPTY',1:'COMMITTED',2:'INCOMPLETE_DAMAGED_OR_UNSUPPORTED',3:'COMMITTED_WITH_QUARANTINE',4:'ACKNOWLEDGED',5:'CLEARED',6:'CLEAR_PENDING',7:'JOURNAL_UNCERTAIN'}
        print(f"Recovery: {states.get(result>>24,'UNKNOWN')}; validated flash pairs={result & 0xffffff}")
        print("Read-only scan; no data erased/repaired. Unknown blocks remain protected.")

    def do_flash_scratch(self, arg):
        """Bench-only: flash_scratch inspect|torn|commit|corrupt|valid|erase; writes ONLY block 7."""
        operation=arg.strip().lower()
        actions={'torn':1,'commit':2,'corrupt':3,'valid':4,'erase':5}
        if operation not in (*actions,'inspect'):
            print("Usage: flash_scratch inspect|torn|commit|corrupt|valid|erase")
            return
        if not self._recovery_ready(): return
        if operation=='inspect':
            try:
                data=self._flash_read_block(7)
                if data==b'\xff'*1024: result='ERASED_BYTES_OBSERVED (not proof of electrical erase quality)'
                else:
                    try: validate_block(data,1); result='VALID_FIXTURE_ENVELOPE'
                    except ValueError as exc: result=f'INVALID_OR_UNCOMMITTED: {exc}'
                directory=self.output_dir/('scratch_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
                directory.mkdir(parents=True,exist_ok=False)
                (directory/'block7.bin').write_bytes(data)
                print(f"Scratch block 7: {result}. Saved {directory.resolve()}")
            except (ValueError,OSError) as exc: print(f"Scratch inspection failed: {exc}")
            return
        print(f"Bench {operation}: modifying ONLY scratch block 7 at 0x21C00; committed recording must verify.")
        result=self._recv_u32_response(0x1c,timeout=30,value_u32=0x53524300|actions[operation])
        if self._flash_result(result):
            print("Scratch operation completed; committed recording reverified by MCU.")
            print("This fixture is not evidence of power loss during an active flash operation.")

    def _lifecycle_action(self, arg, command):
        path=Path(arg.strip())
        if not arg.strip():
            print("Usage: ack_flash <recording.bin path> OR clear_flash <recording.bin path>")
            return
        try:
            evidence=verified_file(path)
        except (ValueError,OSError) as exc:
            print(f"No command sent: saved recording could not be verified/flushed: {exc}")
            return
        if evidence.get("bench_injection"):
            print("Bench RAM cannot be ACKed/cleared as flash. Use measured_bench_discard for its matching saved file.");return
        if not self._flash_ready(): return
        if evidence.get("format_version",1)==2 and not self._measured_ready(): return
        if self._flash_capability not in (0x49500103, 0x49500104):
            print("Lifecycle capability requires firmware 0.0.3.240. No lifecycle command sent.")
            return
        request=uuid.uuid4()
        words=request.bytes+evidence['recording_id'].bytes
        for i in range(8):
            value=int.from_bytes(words[i*4:i*4+4],'big')
            if not self._flash_result(self._recv_u32_response(0x20+i,value_u32=value)):return
        action='Acknowledging verified transfer of' if command==0x28 else 'Explicitly deleting'
        print(f"{action} {evidence['recording_id']} ({evidence['count']} pairs).")
        result=self._recv_u32_response(command,timeout=90,value_u32=evidence['manifest_crc'])
        if not self._flash_result(result):return
        if command==0x28:
            if result!=evidence['count']:
                print("Unexpected ACK count; query flash_recovery before proceeding")
                return
            print("ACK durable. Local flash recording retained; clear_flash is a separate command.")
        elif result==0:
            print("Specified recording cleared. Host file retained. flash_capture can start a NEW UUID without MCU reset.")
        else: print("Unexpected clear response; query flash_recovery")

    def do_ack_flash(self, arg):
        """ack_flash <recording.bin>: verify/flush saved binary and durably ACK matching module recording."""
        self._lifecycle_action(arg,0x28)

    def do_clear_flash(self, arg):
        """clear_flash <recording.bin>: explicitly delete the matching ACKNOWLEDGED recording; keep host copy."""
        self._lifecycle_action(arg,0x29)

    def do_flash_capture(self, arg):
        """flash_capture <pairs>: new bounded RAM capture, no flash writes yet."""
        try:
            limit = int(arg.strip())
            if not 1 <= limit <= 4094: raise ValueError()
        except ValueError:
            print("Usage: flash_capture <1..4094> (actual configured capacity may be lower)")
            return
        if not self._flash_ready(): return
        recording = uuid.uuid4()
        for i in range(4):
            value = int.from_bytes(recording.bytes[i*4:i*4+4], 'big')
            if not self._flash_result(self._recv_u32_response(0x10+i, value_u32=value)): return
        result = self._recv_u32_response(0x14, value_u32=limit)
        if self._flash_result(result):
            print(f"Capture accepted: {recording}, limit={result} pairs. Auto-stops at limit.")
            print("No realtime CSV is created. Use flash_status, then persist_buffer.")

    def do_flash_stop(self, arg):
        """Stop bounded capture early, preserving its RAM samples."""
        if not self._flash_ready(): return
        if self._flash_result(self._recv_u32_response(self.CMD_STOP_STREAM)):
            print("Acquisition stopped; RAM preserved. Check flash_status.")

    def do_flash_status(self, arg):
        """Read stage-one state and current RAM sample count; never modifies storage."""
        if not self._flash_ready(): return
        result = self._recv_u32_response(0x16)
        if self._flash_result(result):
            states = {0:'EMPTY',1:'CAPTURING',2:'RAM_READY',3:'COMMITTED',4:'FAULT',5:'OCCUPIED (unknown/protected media)',6:'CLEARED',7:'CLEAR_PENDING',8:'ACKNOWLEDGED'}
            print(f"Flash state: {states.get(result >> 24, 'UNKNOWN')}; RAM pairs={result & 0xffffff}")

    def do_persist_buffer(self, arg):
        """Persist stopped bounded capture to blank reserved flash; no overwrite/clear."""
        if not self._flash_ready(): return
        print("Persisting and verifying. Acquisition is stopped; CAN may pause. Waiting up to 90 s...")
        result = self._recv_u32_response(0x15, timeout=90)
        if self._flash_result(result): print(f"Committed and readback verified: {result} pairs.")

    def do_verify_flash(self, arg):
        """Read-only MCU verification of v1/v2 manifest/data/metadata/event integrity."""
        if not self._flash_ready(): return
        result = self._recv_u32_response(0x17, timeout=15)
        if self._flash_result(result): print(f"Flash CRC/readback verification passed: {result} pairs.")

    def _flash_read_block(self, block_index):
        return self._tagged_read_block(0x18, 0x1a, block_index)

    def _tagged_read_block(self, command, tag, block_index):
        self._drain_pending_can_messages()
        count = self._recv_u32_response(command, value_u32=block_index)
        if count != 256: raise ValueError(f"Block read rejected/unknown: {count}")
        data = bytearray()
        deadline = time.monotonic()+15
        while len(data)<1024 and time.monotonic()<deadline:
            with self.bus_lock:
                msg = self._recv_frame(0.5)
            if msg is None or msg.arbitration_id != PC_RESP_ID or len(msg.data)!=8 or msg.data[3]!=tag:
                continue
            seq = (msg.data[1]<<8)|msg.data[2]
            if seq != len(data)//4: raise ValueError("Dropped/reordered flash transfer frame; retry dump")
            data.extend(msg.data[4:8])
        if len(data)!=1024: raise ValueError("Flash block transfer timed out; recording unchanged")
        return bytes(data)

    def do_dump_flash(self, arg):
        """dump_flash [stem]: verify/download actual flash to unique binary + nominal CSV files."""
        if not self._flash_ready(): return
        stem = arg.strip() or 'flash_recording'
        if Path(stem).name != stem or stem in ('.','..'):
            print("Use a filename stem without directories")
            return
        try:
            manifest = self._flash_read_block(2)
            if manifest[4:6]==b'\x02\0':
                image=download_v2(self._flash_read_block,manifest)
                directory=self.output_dir/(stem+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
                meta=export_v2(image,directory,'MCU_FLASH')
                print(f"Verified {meta['summary']['samples']} measured flash pairs; saved to {directory.resolve()}")
                print("Raw MCU trigger ticks; UTC unavailable. No ACK/deletion sent. Binary is reconstructed.")
                return
            count, blocks, _ = manifest_info(manifest)
            data = [self._flash_read_block(9+i) for i in range(blocks)]
            samples = validate_recording(manifest, data)
            directory = self.output_dir / (stem+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            directory.mkdir(parents=True, exist_ok=False)
            image = bytearray(b'\xff'*131072)
            image[2048:3072] = manifest
            for i, block in enumerate(data): image[(9+i)*1024:(10+i)*1024] = block
            (directory/'recording.bin').write_bytes(image)
            with (directory/'samples.csv').open('x', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['Timestamp','SampleIndex','Pressure1','Pressure2','SessionId','NominalTimeUs','TimeBasis'])
                for index,p1,p2 in samples:
                    writer.writerow(['',index,p1,p2,str(uuid.UUID(bytes=manifest[8:24])),index*1000,'NOMINAL_ONLY_TIME_UNCERTAIN'])
            print(f"Verified {count} flash pairs; saved to {directory.resolve()}")
            print("Binary is a reconstructed partition: untransferred areas filled FF, not a full physical dump.")
            print("No acknowledgement or deletion sent. CSV time is nominal, not measured acquisition time.")
        except (ValueError, OSError) as exc:
            print(f"Flash dump failed: {exc}. Module recording retained.")

    def do_buffer_status(self, arg):
        """Show firmware RAM buffer status."""
        value = self._recv_u32_response(self.CMD_BUFFER_STATUS)
        if value is None:
            print("No buffer status response received.")
            return

        if value <= 2:
            mode_name = {
                0: "stopped",
                1: "realtime",
                2: "buffered",
            }.get(value, f"unknown({value})")

            print("Buffer status:")
            print(f"  mode: {mode_name}")
            print("  capacity: unavailable (legacy firmware status format)")
            print("  count: unavailable (legacy firmware status format)")
            print("  full/wrapped: unavailable (legacy firmware status format)")
            print("  dump active: unavailable (legacy firmware status format)")
            print("  note: rebuild/flash firmware with packed buffer status support for full details.")
            return

        mode = (value >> 28) & 0x0F
        full = bool((value >> 27) & 0x01)
        dumping = bool((value >> 26) & 0x01)
        capacity = (value >> 12) & 0x0FFF
        count = value & 0x0FFF
        mode_name = {
            0: "stopped",
            1: "realtime",
            2: "buffered",
            3: "measured capture",
        }.get(mode, f"unknown({mode})")

        print("Buffer status:")
        print(f"  mode: {mode_name}")
        print(f"  capacity: {capacity}")
        print(f"  count: {count}")
        print(f"  full/wrapped: {'yes' if full else 'no'}")
        print(f"  dump active: {'yes' if dumping else 'no'}")

    def do_readings(self, arg):
        """Display latest locally observed realtime readings."""
        print("Latest locally observed readings:")

        with self.data_lock:
            snapshot = dict(self.sensor_data)

        for sensor, value in snapshot.items():
            print(f"{sensor}: {value if value is not None else 'No data'}")

    def do_dump_buffer(self, arg):
        """Dump buffered sample data from the module (requires stop streaming)."""
        if self.streaming:
            print("Stop streaming before dumping buffered data.")
            return

        # The firmware streams stored/buffered data in response to CMD_STREAM_BUFFER
        # (0x03). Existing firmware may still tag playback frames as CMD_READ_FLASH
        # (0x07), so the PC side accepts that historical frame type.
        if not self.initialize_can_bus():
            print("Failed to initialize CAN bus")
            return

        drained = self._drain_pending_can_messages()
        if drained:
            print(f"Discarded {drained} queued CAN frame(s) before buffer dump request.")

        if not self.send_command(self.CMD_STREAM_BUFFER):
            print("Failed to send buffer dump request")
            return

        print("Buffer dump request sent. Receiving stored samples...")

        samples = []
        record_count = None
        samples_received = 0
        sequence_errors = 0
        legacy_sequence_format = False
        start_time = datetime.datetime.now()
        timeout = 30  # seconds (stored-data playback can take longer on some modules)

        saw_any_data = False
        received_debug_messages = 0
        payload_debug_limit = 5
        next_progress_report = 1000
        while (datetime.datetime.now() - start_time).total_seconds() < timeout:
            with self.bus_lock:
                msg = self._recv_frame(1)
            if not msg or len(msg.data) != 8:
                continue

            cmd_id = msg.data[3]
            value = (msg.data[4] << 24) | (msg.data[5] << 16) | (msg.data[6] << 8) | msg.data[7]

            # Help diagnose why the module is not responding to the buffer playback request.
            # Print the first few received messages while waiting for the response.
            if record_count is None and received_debug_messages < 5:
                print(f"RX  ID=0x{msg.arbitration_id:03X} data={msg.data.hex()} cmd=0x{cmd_id:02X}")
                received_debug_messages += 1

            if msg.arbitration_id != PC_RESP_ID:
                continue

            # First response should be the buffered-stream reply: command=CMD_STREAM_BUFFER
            # and value = number of stored records (may be 0).
            if cmd_id == self.CMD_STREAM_BUFFER:
                if value & 0x80000000:
                    print("RAM dump rejected by module; for measured capture use dump_measured LABEL.")
                    return
                record_count = value
                print(f"Buffered record count: {record_count}")
                if record_count == 0:
                    break
                continue

            if record_count is None:
                if cmd_id == self.CMD_READ_FLASH:
                    print("Ignoring buffered payload/end frame received before record count.")
                else:
                    print(f"Ignoring response cmd=0x{cmd_id:02X} while waiting for buffer count.")
                continue

            # Show all incoming frames (after count) to help diagnose what the module sends
            if record_count is not None and not saw_any_data:
                print("-- now listening for buffered payload frames --")
                saw_any_data = True

            # Buffered playback frames are tagged CMD_BUFFERED_SAMPLE_DATA.
            if cmd_id != self.CMD_BUFFERED_SAMPLE_DATA:
                continue

            # Collect up to record_count samples (don't treat value==0 as terminator)
            if samples_received < record_count:
                seq = (msg.data[1] << 8) | msg.data[2]
                expected_seq = samples_received & 0xFFFF

                if samples_received == 0 and seq == self.CAN_ID:
                    legacy_sequence_format = True
                    print("Legacy buffered payload format detected; sequence check unavailable.")

                if legacy_sequence_format:
                    seq = expected_seq
                elif seq != expected_seq:
                    sequence_errors += 1
                    if sequence_errors <= 5:
                        print(f"Sequence warning: expected {expected_seq}, received {seq}")

                if samples_received < payload_debug_limit:
                    print(f"RECV ID=0x{msg.arbitration_id:03X} seq={seq} cmd=0x{cmd_id:02X} data={msg.data.hex()}")

                p1 = (value >> 16) & 0xFFFF
                p2 = value & 0xFFFF
                samples.append((seq, p1, p2))
                samples_received += 1

                if samples_received >= next_progress_report and samples_received < record_count:
                    print(f"Received {samples_received}/{record_count} buffered samples...")
                    next_progress_report += 1000

            # Stop when we've collected the expected number of samples
            if samples_received >= record_count:
                break

        if record_count is None:
            print("No response received for buffer dump request (cmd 0x03).")
            return

        if record_count == 0:
            print("No buffered records present on the module.")
            return

        if samples_received != record_count:
            print(f"Warning: expected {record_count} samples but received {samples_received}.")
        else:
            print(f"Received all {samples_received} buffered samples.")

        if sequence_errors:
            print(f"Warning: detected {sequence_errors} buffered sample sequence issue(s).")
        elif legacy_sequence_format:
            print("Buffered sample sequence check skipped for legacy firmware payload format.")
        elif samples:
            print("Buffered sample sequence check passed.")

        if samples:
            out_path = self._make_output_path()
            with open(out_path, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Timestamp', 'SampleIndex', 'Pressure1', 'Pressure2'])
                now = datetime.datetime.now()
                for i, (seq, p1, p2) in enumerate(samples):
                    writer.writerow([now.isoformat(timespec="milliseconds"), seq, p1, p2])
            print(f"Saved {len(samples)} samples to {out_path.resolve()}")
        else:
            print("No stored samples received (timeout or empty record)")

    def do_read_flash(self, arg):
        """Backward-compatible alias for dump_buffer."""
        return self.do_dump_buffer(arg)
        
    def default(self, line):
        """Handle numbered commands"""
        if line in self.COMMAND_MAP:
            # Get the corresponding command method
            cmd_name = self.COMMAND_MAP[line]
            cmd_method = getattr(self, f'do_{cmd_name}')
            # Call the method with empty arguments
            return cmd_method('')
        else:
            return super().default(line)
            
    def do_set_channel(self, arg):
        """Set the COM port for the CANable interface (e.g., 'set_channel COM8')"""
        global CAN_CHANNEL
        if arg:
            # Close existing connection if any
            if self.bus:
                self.bus.shutdown()
                self.bus = None
                
            # Update the global channel
            CAN_CHANNEL = arg.strip()
            print(f"CAN channel set to {CAN_CHANNEL}")
            
            # Try to initialize with the new channel
            if self.initialize_can_bus():
                print("Successfully connected to the new channel")
            else:
                print("Failed to connect to the new channel, but it will be used for future connection attempts")
        else:
            print(f"Current CAN channel is {CAN_CHANNEL}")
            print("Usage: set_channel <COM_PORT>")
            print("Example: set_channel COM8")
    
    def do_scan_ports(self, arg):
        """Scan for available CAN interface ports and allow selection"""
        global CAN_CHANNEL
        old = CAN_CHANNEL
        new = select_can_port()
        if new and new != old:
            if self.bus:
                self.bus.shutdown()
                self.bus = None
            print("Port changed — reconnecting on next CAN action.")
    
    def do_system_info(self, arg):
        """Display system information and available ports"""
        print(f"\nSystem Information:")
        print(f"Operating System: {detect_os()}")
        print(f"Platform: {platform.platform()}")
        print(f"Python Version: {platform.python_version()}")
        print(f"Current CAN Channel: {CAN_CHANNEL or 'Not configured'}")
        
        print(f"\nScanning for serial ports...")
        ports = scan_can_ports()
        
        if not ports:
            print("No serial ports found!")
            return
        
        # Separate CAN devices from other ports
        can_ports = [p for p in ports if p['is_can_device']]
        other_ports = [p for p in ports if not p['is_can_device']]
        
        if can_ports:
            print(f"\nDetected CAN Interface Devices ({len(can_ports)}):")
            print("-" * 50)
            for port in can_ports:
                print(f"  Port: {port['device']}")
                print(f"  Description: {port['description']}")
                if port['manufacturer']:
                    print(f"  Manufacturer: {port['manufacturer']}")
                if port['vid_pid'] != ':':
                    print(f"  VID:PID: {port['vid_pid']}")
                if port['serial_number']:
                    print(f"  Serial: {port['serial_number']}")
                print()
        
        if other_ports:
            print(f"Other Serial Ports ({len(other_ports)}):")
            print("-" * 50)
            for port in other_ports:
                print(f"  Port: {port['device']}")
                print(f"  Description: {port['description']}")
                if port['manufacturer']:
                    print(f"  Manufacturer: {port['manufacturer']}")
                if port['vid_pid'] != ':':
                    print(f"  VID:PID: {port['vid_pid']}")
                print()
    
    def do_help(self, arg):
        """List available commands with help text"""
        if arg:
            # Display help for specific command
            super().do_help(arg)
        else:
            # Display general help with numbered commands
            print("Available commands:")
            print("  Command Numbers:")
            for num, cmd in self.COMMAND_MAP.items():
                method = getattr(self, f'do_{cmd}')
                doc = method.__doc__ or ''
                print(f"  {num} - {doc.strip()}")
            print("\n  Commands:")
            names = self.get_names()
            cmds = [n[3:] for n in names if n.startswith('do_')]
            for cmd in sorted(cmds):
                if cmd != 'help':  # Skip help itself
                    method = getattr(self, f'do_{cmd}')
                    doc = method.__doc__ or ''
                    print(f"  {cmd} - {doc.strip()}")

if __name__ == '__main__':
    CANBusCommander().cmdloop()
