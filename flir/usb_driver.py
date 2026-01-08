"""
Low-level USB driver for FLIR One Pro LT.

Handles device detection, configuration, and bulk transfers.
"""

import usb.core
import usb.util
import time
from typing import Optional

# FLIR One Pro LT USB identifiers
VENDOR_ID = 0x09CB
PRODUCT_ID = 0x1996

# USB endpoints
EP_IN = 0x85  # Bulk IN endpoint for frame data

# USB configuration
USB_CONFIG = 3
USB_INTERFACES = [0, 1, 2]

# Buffer size for reads
BUFFER_SIZE = 16384  # 16KB reads


class USBDriver:
    """Low-level USB communication with FLIR One Pro LT."""
    
    def __init__(self):
        self.device: Optional[usb.core.Device] = None
        self._claimed_interfaces: list = []
        self._initialized = False
        
    def find_device(self) -> bool:
        """Find and return the FLIR One device."""
        self.device = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        return self.device is not None
    
    def open(self) -> bool:
        """Open and configure the device for streaming."""
        if self.device is None:
            if not self.find_device():
                raise RuntimeError("FLIR One Pro LT not found. Is it connected?")
        
        # Detach kernel driver if attached
        for iface in USB_INTERFACES:
            try:
                if self.device.is_kernel_driver_active(iface):
                    self.device.detach_kernel_driver(iface)
            except usb.core.USBError:
                pass
        
        # Set configuration
        try:
            self.device.set_configuration(USB_CONFIG)
        except usb.core.USBError:
            pass  # May already be configured
        
        # Claim interfaces
        for iface in USB_INTERFACES:
            try:
                usb.util.claim_interface(self.device, iface)
                self._claimed_interfaces.append(iface)
            except usb.core.USBError as e:
                print(f"Warning: Could not claim interface {iface}: {e}")
        
        # Initialize camera for video streaming
        self._initialize()
        
        return True
    
    def _initialize(self):
        """Send initialization sequence to start video streaming.
        
        Based on C driver analysis:
        - bmRequestType = 0x01 (USB_TYPE_STANDARD | USB_RECIP_INTERFACE)
        - bRequest = 0x0b (SET_INTERFACE)
        - wValue = alternate setting (0=stop, 1=start)
        - wIndex = interface number (1=FILEIO, 2=FRAME)
        """
        try:
            # Stop interface 2 (FRAME)
            print("stop interface 2 FRAME")
            self.device.ctrl_transfer(0x01, 0x0b, 0, 2, timeout=100)
            
            # Stop interface 1 (FILEIO)
            print("stop interface 1 FILEIO")
            self.device.ctrl_transfer(0x01, 0x0b, 0, 1, timeout=100)
            
            # Start interface 1 (FILEIO)
            print("\nstart interface 1 FILEIO")
            self.device.ctrl_transfer(0x01, 0x0b, 1, 1, timeout=100)
            
            time.sleep(0.1)
            
            # Now we should be able to read from EP 0x85
            print("\nAsk for video stream, start EP 0x85:")
            self._initialized = True
            
        except usb.core.USBError as e:
            print(f"Init error: {e}")
    
    def read(self, timeout: int = 1000) -> Optional[bytes]:
        """Read a chunk of data from the bulk endpoint.
        
        Args:
            timeout: USB read timeout in milliseconds
            
        Returns:
            Bytes read, or None on timeout/error
        """
        if self.device is None:
            return None
        
        try:
            data = self.device.read(EP_IN, BUFFER_SIZE, timeout=timeout)
            return bytes(data)
        except usb.core.USBTimeoutError:
            return None
        except usb.core.USBError as e:
            if e.errno in (110, 19):  # Timeout or No such device
                return None
            print(f"USB read error: {e}")
            return None
    
    def close(self):
        """Release device resources."""
        if self.device is not None:
            # Try to stop streams
            try:
                self.device.ctrl_transfer(0x01, 0x0b, 0, 2, timeout=100)
            except:
                pass
            try:
                self.device.ctrl_transfer(0x01, 0x0b, 0, 1, timeout=100)
            except:
                pass
            
            # Release claimed interfaces
            for iface in self._claimed_interfaces:
                try:
                    usb.util.release_interface(self.device, iface)
                except usb.core.USBError:
                    pass
            
            self._claimed_interfaces = []
            self.device = None
            self._initialized = False
    
    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
