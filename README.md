# MasterPython – Inkley Sensor CAN Interface

Python-based command-line interface for communicating with Inkley hydrodynamic sensor modules over CAN bus.

Designed for laboratory testing, firmware validation, and data logging within the Inkley Sensor Module ecosystem.

---

## Overview

This application enables:

- Real-time pressure and temperature streaming
- Buffered CAN message retrieval
- Intelligent CAN port detection
- Cross-platform compatibility
- Automated CSV logging

Built for use with CANable, CANdo, and other SLCAN-compatible USB CAN interfaces.

---

## Requirements

    pip install python-can pyserial

---

## Supported CAN Interfaces

Automatically detects:

- CANable
- CANdo
- CANtact
- USB2CAN
- PEAK CAN
- Kvaser
- STM32-based CAN devices

---

## Project Structure

    MasterPython/
    │
    ├── InkleySensor.py
    ├── Archive/
    ├── Data/
    ├── CHANGES.md
    └── README.md

---

## Quick Start

### Launch Application

    python InkleySensor.py

### If No Port Configured

Select:

    6 – Scan and select CAN ports

Or manually:

    set_channel COM8

---

## Menu Options

1. Display firmware version  
2. Start real-time streaming  
3. Stream buffered data  
4. Stop streaming  
5. Display current readings  
6. Scan and select CAN ports  
7. Show system information  
8. Exit  

---

## Sensor Channels

- Pressure1  
- Pressure2  
- Temperature1  
- Temperature2  

Data automatically logs to:

    Data/Inkley_sensor_data.csv

---

## CAN Configuration

- Interface: SLCAN  
- Bitrate: 1 Mbps  
- CAN ID: 0x107  
- Frame Size: 8 bytes  

---

## Port Detection Logic

The application:

1. Scans all serial ports  
2. Identifies likely CAN devices using:
   - Keywords
   - Manufacturer strings
   - VID/PID matching
3. Separates CAN candidates from other devices  
4. Displays detailed port metadata  

---

## Cross-Platform Support

### Windows
- Detects COM ports
- Compatible with SLCAN devices

### macOS
- Detects /dev/tty.* and /dev/cu.* devices

### Linux
- Detects /dev/ttyUSB*, /dev/ttyACM*, and other serial devices

---

## Troubleshooting

### No Ports Found
- Verify USB connection
- Install drivers
- Try running as administrator

### Linux Permissions

    sudo usermod -a -G dialout $USER

---

## Development Notes

Key functions:

- detect_os()
- scan_can_ports()
- select_can_port()
- initialize_can_bus()

Planned improvements:
- Configuration file support
- Auto-connect to last used port
- Logging configuration options
- Improved data parsing architecture

---

## Context

Part of the broader Inkley Sensor Module development effort for distributed hydrodynamic sensing and CAN-enabled underwater instrumentation.
