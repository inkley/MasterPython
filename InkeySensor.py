import can

# Candlelight firmware on Linux
#bus = can.interface.Bus(bustype='socketcan', channel='can0', bitrate=500000)

# Stock slcan firmware on Linux
# bus = can.interface.Bus(bustype='slcan', channel='/dev/ttyACM0', bitrate=500000)
def send_one():

    bus = can.interface.Bus(interface='slcan', channel='COM8', bitrate=1000000)

    msg = can.Message(arbitration_id=0x107,
                    data=[0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], #Read Sensor Module Version.
                    is_extended_id=False)

    try:
        bus.send(msg)
        print("Message sent on {}".format(bus.channel_info))
    except can.CanError:
        print("Message NOT sent")


if __name__ == "__main__":
    send_one()