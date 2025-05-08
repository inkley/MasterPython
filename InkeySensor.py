import can
import csv
import datetime
import struct
import cmd
import threading

class CANBusCommander(cmd.Cmd):
    intro = "Inkley Sensor Command Line Interface. Type 'help' for commands.\n"
    prompt = "> "

    def __init__(self):
        super().__init__()
        self.bus = None
        self.streaming = False
        self.stream_thread = None
        self.csv_file = 'Inkley_sensor_data.csv'
        self.sensor_data = {
            'Pressure1': '',
            'Pressure2': '',
            'Temperature1': '',
            'Temperature2': ''
        }
        # Define CAN ID and sensor IDs
        self.CAN_ID = 0x7DF
        self.SENSOR_IDS = {
            0x01: 'Pressure1',
            0x02: 'Pressure2',
            0x03: 'Temperature1',
            0x04: 'Temperature2'
        }
        self.version = "1.0.0"

    def parse_sensor_value(self, data):
        if len(data) >= 6 and data[0] == 5:  # Check length byte
            raw_value = data[2:6]
            return struct.unpack('>i', bytes(raw_value))[0]
        return None

    def stream_data(self):
        # Initialize CAN bus interface for CANable
        # * don't forget to choose the right COM port.
        #Mac
        #bus = can.interface.Bus(bustype='slcan', channel='/dev/ttyUSB0', bitrate=1000000)

        #Windows
        bus = can.interface.Bus(interface='slcan', channel='COM8', bitrate=1000000)
        
        with open(self.csv_file, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Timestamp', 'Pressure1', 'Pressure2', 'Temperature1', 'Temperature2'])
            last_write_time = datetime.datetime.now()

            try:
                while self.streaming:
                    for msg in self.bus:
                        if not self.streaming:
                            break
                        current_time = datetime.datetime.now()
                        
                        if msg.arbitration_id == self.CAN_ID and len(msg.data) == 8:
                            sensor_id = msg.data[1]
                            if sensor_id in self.SENSOR_IDS:
                                value = self.parse_sensor_value(msg.data)
                                if value is not None:
                                    self.sensor_data[self.SENSOR_IDS[sensor_id]] = str(value)

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
                self.bus.shutdown()
                self.bus = None
                print(f"CAN sensor data saved to {self.csv_file}")

    def do_version(self, arg):
        """Display the version of the CAN bus interface"""
        print(f"Version: {self.version}")

    def do_start(self, arg):
        """Start real-time CAN bus streaming"""
        if not self.streaming:
            self.streaming = True
            self.stream_thread = threading.Thread(target=self.stream_data)
            self.stream_thread.start()
            print("Started real-time streaming")
        else:
            print("Streaming is already active")

    def do_stop(self, arg):
        """Stop real-time CAN bus streaming"""
        if self.streaming:
            self.streaming = False
            if self.stream_thread:
                self.stream_thread.join()
            print("Stopped real-time streaming")
        else:
            print("Streaming is not active")

    def do_quit(self, arg):
        """Exit the command line interface"""
        if self.streaming:
            self.streaming = False
            if self.stream_thread:
                self.stream_thread.join()
        print("Exiting Sensor Commander")
        return True

    def do_exit(self, arg):
        """Alias for quit command"""
        return self.do_quit(arg)

if __name__ == '__main__':
    CANBusCommander().cmdloop()
