import can

with can.interface.Bus(interface='slcan', channel='COM5', bitrate=500000) as bus:

    msg = can.Message(
        arbitration_id=0xc0ffee,
        data=[0, 25, 0, 1, 3, 1, 4, 1],
        is_extended_id=True
    )

    try:
        bus.send(msg)
        print(f"Message sent on {bus.channel_info}")
    except can.CanError:
        print("Message NOT sent")
