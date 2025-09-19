# Inkley Sensor CAN Interface

A Python-based command-line interface for communicating with Inkley sensor modules via CAN bus using CANable/CANdo serial interfaces.

## Features

### Core Functionality
- Real-time sensor data streaming
- Buffered data streaming
- Individual sensor readings
- CSV data logging
- Firmware version checking

### New Cross-Platform Features
- **OS Detection**: Automatically detects Windows, macOS, and Linux
- **Smart Port Scanning**: Scans for available serial ports and identifies likely CAN interface devices
- **Interactive Port Selection**: User-friendly interface to select from detected ports
- **System Information**: Displays comprehensive system and port information

## Requirements

```bash
pip install python-can pyserial
```

## Supported CAN Interfaces

The application automatically detects common CAN interface devices including:
- CANable
- CANdo
- CANtact
- USB2CAN
- PEAK CAN
- Kvaser
- Generic STM32-based CAN devices

## Usage

### Starting the Application

```bash
python InkeySensor.py
```

### Menu Options

1. **Display version** - Get sensor module firmware version
2. **Start real-time streaming** - Begin continuous data streaming
3. **Stream buffered data** - Stream previously buffered sensor data
4. **Stop streaming** - Stop active data streaming
5. **Display current readings** - Show current sensor values
6. **Scan and select CAN ports** - Scan for available CAN interfaces and select one
7. **Show system information** - Display OS, platform, and port information
8. **Exit program** - Close the application

### Additional Commands

- `set_channel <PORT>` - Manually set the CAN interface port (e.g., `set_channel COM8`)
- `scan_ports` - Scan for available CAN interface ports
- `system_info` - Display system and port information
- `help` - Show available commands

## Port Detection

The application uses intelligent port detection that:

1. **Scans all available serial ports** on the system
2. **Identifies CAN devices** by checking:
   - Device descriptions for CAN-related keywords
   - Manufacturer information
   - USB Vendor ID/Product ID (VID/PID) combinations
3. **Separates likely CAN devices** from other serial ports
4. **Provides detailed information** including:
   - Port name (COM8, /dev/ttyUSB0, etc.)
   - Device description
   - Manufacturer
   - VID:PID
   - Serial number

## Cross-Platform Support

### Windows
- Detects COM ports (COM1, COM8, etc.)
- Supports CANable devices via SLCAN interface

### macOS
- Detects /dev/tty.* and /dev/cu.* devices
- Full support for USB CAN interfaces

### Linux
- Detects /dev/ttyUSB*, /dev/ttyACM*, and other serial devices
- Compatible with various CAN interface drivers

## Sensor Data

The application handles four sensor channels:
- **Pressure1** - Primary pressure sensor
- **Pressure2** - Secondary pressure sensor  
- **Temperature1** - Primary temperature sensor
- **Temperature2** - Secondary temperature sensor

Data is automatically logged to `Inkley_sensor_data.csv` with timestamps.

## CAN Protocol

- **Interface**: SLCAN (Serial Line CAN)
- **Bitrate**: 1 Mbps
- **CAN ID**: 0x107
- **Message Format**: 8-byte CAN frames with structured data

## Example Usage

```bash
# Start the application
python InkeySensor.py

# The application will show available ports if none configured
> 6  # Select option 6 to scan ports

# Or manually set a port
> set_channel COM8

# Check system information
> 7  # Shows OS, platform, and available ports

# Start streaming data
> 2  # Begin real-time streaming

# Stop streaming
> 4  # Stop data collection

# Exit
> 8  # Exit application
```

## Troubleshooting

### No Ports Found
- Ensure CAN interface device is connected
- Check device drivers are installed
- Try running with administrator/sudo privileges

### Connection Issues
- Verify correct port selection
- Check CAN interface is in SLCAN mode
- Ensure proper bitrate configuration (1 Mbps)

### Permission Issues (Linux/macOS)
```bash
# Add user to dialout group (Linux)
sudo usermod -a -G dialout $USER

# Or run with sudo
sudo python InkeySensor.py
```

## Development

The codebase includes:
- `detect_os()` - Cross-platform OS detection
- `scan_can_ports()` - Intelligent port scanning with CAN device identification
- `select_can_port()` - Interactive port selection interface
- Enhanced command-line interface with numbered menu options

## License

This project is part of the Inkley sensor ecosystem for CAN bus communication and data logging.