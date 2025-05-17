import can
import csv
import datetime
import struct
import cmd
import threading

# Global configuration
CAN_CHANNEL = 'COM8'  # Set the COM port for the CANable interface

class CANBusCommander(cmd.Cmd):
    intro = """Inkley Sensor Command Line Interface. Type 'help' for commands.
Inkey Sensor CLI Menu:
  1 - Display version
  2 - Start real-time streaming
  3 - Stream buffered data
  4 - Stop streaming
  5 - Display current readings
  6 - Exit program

Additional commands:
  set_channel - Set the COM port for the CANable interface
"""
    prompt = "> "
    
    # Define command numbers for quick access
    COMMAND_MAP = {
        '1': 'version',
        '2': 'start',
        '3': 'stream_buffer',
        '4': 'stop',
        '5': 'readings',
        '6': 'quit'
    }

    def __init__(self):
        super().__init__()
        self.bus = None
        self.streaming = False
        self.stream_thread = None
        self.csv_file = 'Inkley_sensor_data.csv'
        # Print the current CAN channel at startup
        print(f"Using CAN channel: {CAN_CHANNEL}")
        self.sensor_data = {
            'Pressure1': '',
            'Pressure2': '',
            'Temperature1': '',
            'Temperature2': ''
        }
        # Define CAN ID and sensor IDs
        self.CAN_ID = 0x107  # Updated to new sensor module CAN ID
        self.SENSOR_IDS = {
            0x01: 'Pressure1',
            0x02: 'Pressure2',
            0x03: 'Temperature1',
            0x04: 'Temperature2'
        }
        # Command IDs for sending to the sensor module
        self.CMD_VERSION = 0x01
        self.CMD_START_STREAM = 0x02
        self.CMD_STREAM_BUFFER = 0x03
        self.CMD_STOP_STREAM = 0x04
        self.CMD_GET_READINGS = 0x05
        
        self.version = "1.0.0"

    def parse_sensor_value(self, data):
        """Parse sensor data based on the response format
        
        Format:
        - First byte: Length of the data
        - Next two bytes: CAN ID of the sensor module
        - Next byte: Command that was sent
        - Next four bytes: Returned value
        """
        # Check if we have enough data
        if len(data) < 8:  # Need at least 8 bytes for a complete response
            return None
            
        # Extract the components
        length = data[0]
        # CAN ID is in bytes 1-2 (we don't need to use it here)
        command_id = data[3]  # Command is in byte 3
        
        # For all commands that return a 4-byte value
        if length >= 7 and len(data) >= 8:  # Length should be at least 7 for command + 4 bytes of data
            raw_value = data[4:8]  # Value is in bytes 4-7
            return struct.unpack('>i', bytes(raw_value))[0]
            
        return None
        
    def initialize_can_bus(self):
        """Initialize the CAN bus if not already initialized"""
        if self.bus is None:
            try:
                # Use the global CAN_CHANNEL variable
                self.bus = can.interface.Bus(interface='slcan', channel=CAN_CHANNEL, bitrate=1000000)
                print(f"CAN bus initialized successfully on {CAN_CHANNEL}")
                return True
            except Exception as e:
                print(f"Error initializing CAN bus on {CAN_CHANNEL}: {e}")
                return False
        return True
        
    def send_command(self, command_id, data=None):
        """Send a command to the sensor module via CAN bus"""
        if not self.initialize_can_bus():
            return False
                
        # Prepare message data - first byte is command ID
        message_data = [command_id]
        
        # Add additional data if provided
        if data:
            message_data.extend(data)
            
        # Pad to 8 bytes if necessary
        while len(message_data) < 8:
            message_data.append(0x00)
            
        # Create and send the CAN message
        try:
            msg = can.Message(
                arbitration_id=self.CAN_ID,
                data=message_data,
                is_extended_id=False
            )
            self.bus.send(msg)
            print(f"Sent command {hex(command_id)} to sensor module")
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

    def stream_data(self):
        # Initialize CAN bus interface for CANable
        try:
            if not self.initialize_can_bus():
                print("Failed to initialize CAN bus")
                return
            
            with open(self.csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(['Timestamp', 'Pressure1', 'Pressure2', 'Temperature1', 'Temperature2'])
                last_write_time = datetime.datetime.now()

                while self.streaming:
                    for msg in self.bus:
                        if not self.streaming:
                            break
                        current_time = datetime.datetime.now()
                        
                        # Process all CAN messages with the expected format
                        if len(msg.data) >= 8:  # Need at least 8 bytes for a complete response
                            # Extract the components based on the format
                            length = msg.data[0]
                            # CAN ID is in bytes 1-2
                            command_id = msg.data[3]  # Command is in byte 3
                            
                            # Handle version response separately
                            if command_id == self.CMD_VERSION and len(msg.data) >= 8:
                                # For version, the 4 bytes contain major, minor, patch, build
                                major = msg.data[4]
                                minor = msg.data[5]
                                patch = msg.data[6]
                                build = msg.data[7]
                                version_str = f"{major}.{minor}.{patch}.{build}"
                                print(f"Received sensor module firmware version: {version_str}")
                                # Update local version
                                self.version = version_str
                            
                            # Handle sensor data for other commands
                            elif command_id in [self.CMD_START_STREAM, self.CMD_STREAM_BUFFER, self.CMD_GET_READINGS]:
                                # The sensor ID is included in the response
                                sensor_id = msg.data[4]  # Assuming sensor ID is the first byte of the value
                                
                                if sensor_id in self.SENSOR_IDS:
                                    # Parse the remaining 3 bytes as the actual value
                                    if len(msg.data) >= 8:
                                        # Use the last 3 bytes for the value (assuming it's a 3-byte value)
                                        raw_value = bytes([0]) + bytes(msg.data[5:8])  # Pad with a zero byte for 4-byte int
                                        value = struct.unpack('>i', raw_value)[0]
                                        self.sensor_data[self.SENSOR_IDS[sensor_id]] = str(value)
                                        print(f"Received {self.SENSOR_IDS[sensor_id]} value: {value}")

                        if (current_time - last_write_time).total_seconds() >= 1:
                            writer.writerow([
                                current_time.isoformat(),
                                self.sensor_data['Pressure1'],
                                self.sensor_data['Pressure2'],
                                self.sensor_data['Temperature1'],
                                self.sensor_data['Temperature2']
                            ])
                            last_write_time = current_time
        except Exception as e:
            print(f"Streaming error: {e}")
        finally:
            if self.bus:
                self.bus.shutdown()
                self.bus = None
            print(f"Sensor data saved to {self.csv_file}")

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
                    msg = self.bus.recv(1)  # 1 second timeout for each recv call
                    
                    if msg and len(msg.data) >= 8:
                        # Check if this is a version response based on the format
                        length = msg.data[0]
                        # CAN ID is in bytes 1-2
                        command_id = msg.data[3]  # Command is in byte 3
                        
                        if command_id == self.CMD_VERSION:
                            # For version, the 4 bytes contain major, minor, patch, build
                            major = msg.data[4]
                            minor = msg.data[5]
                            patch = msg.data[6]
                            build = msg.data[7]
                            version_str = f"{major}.{minor}.{patch}.{build}"
                            print(f"Sensor module firmware version: {version_str}")
                            # Update local version
                            self.version = version_str
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
                self.stream_thread = threading.Thread(target=self.stream_data)
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
                self.stream_thread = threading.Thread(target=self.stream_data)
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
            for sensor, value in self.sensor_data.items():
                print(f"{sensor}: {value or 'No data'}")
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
            CAN_CHANNEL = arg
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
