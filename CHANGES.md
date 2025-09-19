# Changes Made to InkeySensor.py

## Summary
Added cross-platform OS detection and intelligent CAN port scanning functionality to the Inkley Sensor CAN Interface.

## New Dependencies
```python
import platform          # For OS detection
import serial.tools.list_ports  # For serial port scanning
import re                # For pattern matching (imported but not used in final version)
```

## New Global Functions

### `detect_os()`
- Detects the current operating system (Windows, macOS, Linux)
- Returns user-friendly OS names
- Handles unknown systems gracefully

### `scan_can_ports()`
- Scans all available serial ports on the system
- Identifies likely CAN interface devices using:
  - Device description keywords (canable, cando, slcan, etc.)
  - Manufacturer information
  - Common CAN device VID/PID combinations
- Returns detailed port information including:
  - Device path
  - Description
  - Manufacturer
  - VID:PID
  - Serial number
  - CAN device classification

### `select_can_port()`
- Interactive port selection interface
- Separates likely CAN devices from other serial ports
- Provides numbered menu for easy selection
- Allows manual port entry
- Handles user cancellation gracefully
- Updates global `CAN_CHANNEL` variable

## Modified Code Sections

### Global Configuration
```python
# Changed from hardcoded COM8 to dynamic selection
CAN_CHANNEL = None  # Will be set after port detection/selection
```

### Class Initialization (`__init__`)
- Removed automatic port selection on startup (to avoid blocking)
- Added informative message about port configuration options
- Enhanced startup messaging

### CAN Bus Initialization (`initialize_can_bus`)
- Added check for `CAN_CHANNEL = None`
- Provides helpful error message when no port is configured
- Prevents crashes when attempting to connect without a port

### New Menu Commands

#### Updated Menu (intro)
- Added option 6: "Scan and select CAN ports"
- Added option 7: "Show system information"  
- Updated option 8: "Exit program" (was option 6)
- Added documentation for new commands

#### Updated Command Map
```python
COMMAND_MAP = {
    '1': 'version',
    '2': 'start',
    '3': 'stream_buffer', 
    '4': 'stop',
    '5': 'readings',
    '6': 'scan_ports',      # NEW
    '7': 'system_info',     # NEW
    '8': 'quit'             # Updated number
}
```

### New Command Methods

#### `do_scan_ports(self, arg)`
- Calls the interactive port selection function
- Allows users to scan and select ports from within the CLI

#### `do_system_info(self, arg)`
- Displays comprehensive system information:
  - Operating system and platform details
  - Python version
  - Current CAN channel configuration
  - All available serial ports with detailed information
  - Separates likely CAN devices from other ports

## Enhanced Features

### Cross-Platform Compatibility
- **Windows**: Detects COM ports (COM1, COM8, etc.)
- **macOS**: Detects /dev/tty.* and /dev/cu.* devices  
- **Linux**: Detects /dev/ttyUSB*, /dev/ttyACM*, etc.

### Intelligent Device Detection
The system recognizes CAN interfaces by checking for:
- **Keywords**: canable, cando, slcan, can, cantact, usb2can, peak, kvaser
- **VID/PID combinations**:
  - `1D50:606F` - CANable
  - `16C0:27DD` - CANtact  
  - `0483:5740` - STM32 (common for CAN devices)

### User Experience Improvements
- Clear separation of likely CAN devices from other serial ports
- Detailed device information display
- Non-blocking startup (doesn't force port selection immediately)
- Graceful handling of systems with no serial ports
- Option to skip port selection or enter custom ports

## Installation Requirements
Added requirement for `pyserial` package:
```bash
pip install pyserial
```

## Backward Compatibility
- All existing functionality preserved
- Existing command numbers still work (except quit moved from 6 to 8)
- Manual port setting via `set_channel` still available
- Original CAN communication protocol unchanged

## Error Handling
- Graceful handling of systems with no serial ports
- Clear error messages when no CAN channel is configured
- Proper exception handling in port scanning
- User-friendly messages for connection issues