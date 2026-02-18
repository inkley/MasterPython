"""
Author: Tyler Inkley

Inkley_SensorCommander (Python CLI)
- Command-line interface for interacting with the Inkley/Tiva pressure sensor module over CAN (SLCAN/CANable).
- Supports:
    * Query firmware version (ACK via PC_RESP_ID)
    * Start/stop real-time streaming
    * Stream buffered mode (placeholder on firmware side if not implemented)
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
from pathlib import Path

# Global configuration
CAN_CHANNEL = 'COM5'

# NEW: the CAN ID PC/listener will receive ACK responses on
PC_RESP_ID = 0x108

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
Inkey Sensor CLI Menu:
  1 - Display version
  2 - Start real-time streaming
  3 - Stream buffered data
  4 - Stop streaming
  5 - Display current readings
  6 - Scan and select CAN ports
  7 - Show system information
  8 - Exit program

Additional commands:
  set_channel      - Set the COM port for the CANable interface
  scan_ports       - Scan for available CAN interface ports
  system_info      - Display OS and port information
  set_outdir       - Set output directory for CSV logging
  set_filename     - Set CSV filename for logging
"""
    prompt = "> "
    
    # Define command numbers for quick access
    COMMAND_MAP = {
        '1': 'version',
        '2': 'start',
        '3': 'stream_buffer',
        '4': 'stop',
        '5': 'readings',
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

        # NEW: lock to protect shared data between CLI thread + stream thread
        self.data_lock = threading.Lock()

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
        
        self.version = "1.0.0"
        
    def initialize_can_bus(self):
        """Initialize the CAN bus if not already initialized"""
        if self.bus is None:
            if CAN_CHANNEL is None:
                print("No CAN channel configured. Use 'scan_ports' or 'set_channel' to configure a port.")
                return False
            try:
                # Use the global CAN_CHANNEL variable
                self.bus = can.interface.Bus(interface='slcan', channel=CAN_CHANNEL, bitrate=500000)
                print(f"CAN bus initialized successfully on {CAN_CHANNEL}")
                return True
            except Exception as e:
                print(f"Error initializing CAN bus on {CAN_CHANNEL}: {e}")
                return False
        return True
        
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
            self.bus.send(msg)
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

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

                while self.streaming:
                    # Wake up at least every 0.1s even if no CAN messages arrive
                    msg = self.bus.recv(timeout=0.1)
                    current_time = datetime.datetime.now()

                    handled = False

                    # Only parse if we actually received a message
                    if msg is not None:
                        # --- Special-case: broadcast realtime frames from Tiva (ID 0x7DF) ---
                        if msg.arbitration_id == 0x7DF and len(msg.data) == 8:
                            frame_type = msg.data[0]
                            sensor_id  = msg.data[1]

                            if frame_type == 0x05:

                                # -------- NEW PACKED MODE --------
                                if sensor_id == 0x12:   # packed P1 + P2
                                    p1 = (msg.data[2] << 8) | msg.data[3]
                                    p2 = (msg.data[4] << 8) | msg.data[5]

                                    with self.data_lock:
                                        self.sensor_data['Pressure1'] = p1
                                        self.sensor_time['Pressure1'] = current_time
                                        self.sensor_data['Pressure2'] = p2
                                        self.sensor_time['Pressure2'] = current_time

                                    # Write every sample (1000 Hz)
                                    writer.writerow([current_time.isoformat(timespec="milliseconds"), p1, p2])

                                    sample_counter += 1   # increment

                                    # Flush every 1000 samples (~1 second at 1 kHz)
                                    if sample_counter % 1000 == 0:
                                        file.flush()

                                   
                                    #print(f"[BC] Pressure1: {p1}  Pressure2: {p2}")
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

                        # Handle ACK/response frames coming back to the PC
                        if msg is not None and msg.arbitration_id == PC_RESP_ID and len(msg.data) == 8:
                            cmd_id = msg.data[3]
                            if cmd_id == self.CMD_VERSION:
                                major, minor, patch, build = msg.data[4], msg.data[5], msg.data[6], msg.data[7]
                                self.version = f"{major}.{minor}.{patch}.{build}"
                                print(f"Received firmware version: {self.version}")
                            else:
                                # Generic status/value in bytes 4..7
                                val = (msg.data[4] << 24) | (msg.data[5] << 16) | (msg.data[6] << 8) | msg.data[7]
                                print(f"ACK cmd={hex(cmd_id)} value={val}")
                            continue

        except Exception as e:
            print(f"Streaming error: {e}")
        finally:
            if self.bus:
                self.bus.shutdown()
                self.bus = None
            print(f"Sensor data saved to {out_path.resolve() if 'out_path' in locals() else self.csv_file}")

    def do_version(self, arg):
        """Display the version of the sensor module firmware"""
        if self.send_command(self.CMD_VERSION):
            print("Version request sent to sensor module. Waiting for response...")
            
            # Wait for response with timeout
            try:
                if not self.initialize_can_bus():
                    print("Failed to initialize CAN bus")
                    return
                    
                # Set a timeout for waiting for the response (5 seconds)
                start_time = datetime.datetime.now()
                timeout = 5  # seconds
                
                while (datetime.datetime.now() - start_time).total_seconds() < timeout:
                    msg = self.bus.recv(1)

                    if msg and msg.arbitration_id == PC_RESP_ID and len(msg.data) == 8:
                        cmd_id = msg.data[3]
                        if cmd_id == self.CMD_VERSION:
                            major, minor, patch, build = msg.data[4], msg.data[5], msg.data[6], msg.data[7]
                            self.version = f"{major}.{minor}.{patch}.{build}"
                            print(f"Sensor module firmware version: {self.version}")
                            return
                
                # If we get here, we timed out waiting for a response
                print("No response received from sensor module. Using local version.")
                print(f"Local version: {self.version}")
                
            except Exception as e:
                print(f"Error receiving version response: {e}")
                print(f"Local version: {self.version}")
        else:
            print("Failed to send version request command")
            print(f"Local version: {self.version}")

    def do_start(self, arg):
        """Start real-time sensor streaming"""
        if not self.streaming:
            if self.send_command(self.CMD_START_STREAM):
                self.streaming = True
                self.stream_thread = threading.Thread(target=self.stream_data, daemon=True)
                self.stream_thread.start()
                print("Started real-time streaming")
            else:
                print("Failed to send start streaming command")
        else:
            print("Streaming is already active")

    def do_stream_buffer(self, arg):
        """Stream buffered sensor streaming"""
        if not self.streaming:
            if self.send_command(self.CMD_STREAM_BUFFER):
                self.streaming = True
                self.stream_thread = threading.Thread(target=self.stream_data, daemon=True)
                self.stream_thread.start()
                print("Started streaming buffered data")
            else:
                print("Failed to send stream buffer command")
        else:
            print("Streaming is already active")

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
        
    def do_readings(self, arg):
        """Display current sensor readings"""
        if self.send_command(self.CMD_GET_READINGS):
            print("Reading request sent to sensor module")
            print("Current sensor readings:")

            with self.data_lock:
                snapshot = dict(self.sensor_data)

            for sensor, value in snapshot.items():
                print(f"{sensor}: {value if value is not None else 'No data'}")
        else:
            print("Failed to send reading request command")
        
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
