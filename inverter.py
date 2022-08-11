import minimalmodbus
import serial


class Inverter(minimalmodbus.Instrument):
    def __init__(self, device, slave_address):
        super().__init__(device, slave_address)
        self.serial.baudrate = 9600
        self.serial.timeout = 1
        self.serial.bytesize = 8
        self.serial.stopbits = 1
        self.serial.parity = serial.PARITY_NONE
