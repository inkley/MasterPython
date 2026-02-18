# MasterPython – Change Log

---

## v1.3 – Cross-Platform CAN Port Detection & CLI Improvements

### Summary
Major usability upgrade adding cross-platform OS detection, intelligent CAN port scanning, and enhanced CLI functionality for the Inkley Sensor CAN Interface.

---

## Added

### Cross-Platform Support
- Automatic OS detection (Windows, macOS, Linux)
- Serial port scanning compatible across platforms
- Graceful handling of systems without serial ports

### New Dependencies
    import platform
    import serial.tools.list_ports
    import re

### New Global Functions

#### detect_os()
- Detects host operating system
- Returns user-friendly OS names
- Handles unknown systems gracefully

#### scan_can_ports()
- Scans all available serial ports
- Identifies likely CAN devices using:
  - Device description keywords
  - Manufacturer information
  - Known CAN VID/PID combinations
- Returns detailed port metadata

#### select_can_port()
- Interactive CLI-based port selection
- Separates likely CAN devices from other serial ports
- Allows manual port entry
- Updates global CAN_CHANNEL
- Handles cancellation gracefully

---

## Modified

### Global Configuration
Replaced hardcoded COM port with dynamic selection:

    CAN_CHANNEL = None

### Class Initialization
- Removed blocking auto-selection
- Improved startup messaging

### initialize_can_bus()
- Added check for CAN_CHANNEL is None
- Improved error messaging
- Prevented startup crashes

---

## CLI Enhancements

### Updated Command Map
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

### New Commands

#### scan_ports
- Scan and select CAN interfaces from CLI

#### system_info
Displays:
- OS and platform info
- Python version
- Current CAN channel
- Detailed port inventory

---

## Intelligent CAN Detection

Recognizes devices using:

Keywords:
- canable
- cando
- slcan
- cantact
- usb2can
- peak
- kvaser

VID/PID Examples:
- 1D50:606F – CANable
- 16C0:27DD – CANtact
- 0483:5740 – STM32-based CAN devices

---

## Installation

    pip install python-can pyserial

---

## Backward Compatibility

- All core functionality preserved
- Manual set_channel still supported
- CAN protocol unchanged
- Command numbering updated (quit moved from 6 to 8)

---

## Notes

- Pressure2 streaming updates integrated
- Data logging improvements ongoing
- Future work: configuration file support and auto-connect profiles
