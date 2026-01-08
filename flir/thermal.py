"""
Thermal data processing utilities.

Converts raw sensor values to temperatures and provides analysis tools.
"""

import numpy as np
from typing import Tuple, Optional

# FLIR One Pro LT calibration constants (approximate)
# These may need adjustment based on camera calibration
DEFAULT_OFFSET = 8617.0  # Planck offset
DEFAULT_SCALE = 0.04     # Planck scale factor


def raw_to_celsius(raw_value: np.ndarray,
                   offset: float = DEFAULT_OFFSET,
                   scale: float = DEFAULT_SCALE) -> np.ndarray:
    """Convert raw thermal sensor values to Celsius.
    
    Note: This is an approximate conversion. The actual FLIR calibration
    uses Planck's law with camera-specific constants stored in metadata.
    
    Args:
        raw_value: Raw 16-bit sensor values
        offset: Temperature offset
        scale: Scale factor
        
    Returns:
        Temperature in Celsius
    """
    # Simplified linear approximation
    # Real FLIR uses: T = B / ln(R1/(R2*(S+O)) + F) - 273.15
    # where B, R1, R2, F, O are camera calibration constants
    
    temp_c = (raw_value.astype(np.float32) - offset) * scale
    return temp_c


def get_temperature_stats(thermal_raw: np.ndarray) -> dict:
    """Calculate temperature statistics from raw thermal data.
    
    Args:
        thermal_raw: 16-bit raw thermal data
        
    Returns:
        Dictionary with min, max, mean, and locations
    """
    temp_c = raw_to_celsius(thermal_raw)
    
    min_idx = np.unravel_index(np.argmin(temp_c), temp_c.shape)
    max_idx = np.unravel_index(np.argmax(temp_c), temp_c.shape)
    
    return {
        'min_c': float(np.min(temp_c)),
        'max_c': float(np.max(temp_c)),
        'mean_c': float(np.mean(temp_c)),
        'min_location': (int(min_idx[1]), int(min_idx[0])),  # (x, y)
        'max_location': (int(max_idx[1]), int(max_idx[0])),
        'raw_min': int(np.min(thermal_raw)),
        'raw_max': int(np.max(thermal_raw)),
    }


def find_hotspot(thermal_raw: np.ndarray) -> Tuple[int, int, float]:
    """Find the hottest point in the thermal image.
    
    Args:
        thermal_raw: 16-bit raw thermal data
        
    Returns:
        (x, y, temperature_celsius) tuple
    """
    max_idx = np.unravel_index(np.argmax(thermal_raw), thermal_raw.shape)
    temp_c = raw_to_celsius(thermal_raw[max_idx[0], max_idx[1]])
    return (int(max_idx[1]), int(max_idx[0]), float(temp_c))


def find_coldspot(thermal_raw: np.ndarray) -> Tuple[int, int, float]:
    """Find the coldest point in the thermal image.
    
    Args:
        thermal_raw: 16-bit raw thermal data
        
    Returns:
        (x, y, temperature_celsius) tuple
    """
    min_idx = np.unravel_index(np.argmin(thermal_raw), thermal_raw.shape)
    temp_c = raw_to_celsius(thermal_raw[min_idx[0], min_idx[1]])
    return (int(min_idx[1]), int(min_idx[0]), float(temp_c))
