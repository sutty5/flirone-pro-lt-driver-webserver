import json
import numpy as np
import os
import sys

class ThermalContext:
    def __init__(self, config_path='camera_config.json'):
        self.config = {
            "PlanckR1": 21106.77,
            "PlanckB": 1506.8,
            "PlanckF": 1.0,
            "PlanckO": -7340,
            "Emissivity": 0.95,
            "ReflectedApparentTemperature": 20.0
        }
        
        # Try to load custom config
        # Look in CWD and project root
        paths = [
            os.path.abspath(config_path), 
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'camera_config.json'))
        ]
        
        loaded = False
        sys.stderr.write(f"Thermal Context Initializing. Checking paths: {paths}\n")
        
        for path in paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        self.config.update(data)
                    sys.stderr.write(f"Loaded calibration from {path}\n")
                    loaded = True
                    break
                except Exception as e:
                    sys.stderr.write(f"Error loading {path}: {e}\n")
        
        if not loaded:
            sys.stderr.write("Using generic calibration constants (Lepton 3.5 defaults)\n")
            
        sys.stderr.write(f"Active PlanckO: {self.config['PlanckO']}\n")

    def raw2temp(self, raw_counts):
        """
        Convert raw 16-bit sensor values to temperature in Celsius.
        Formula: T = B / log(R1 / (R2 * (raw + O)) + F) - 273.15
        Note: R2 is often absorbed/assumed 1 or part of Emissivity calculation.
        Simplified for Flir One: T = B / log(R / (raw - O) + F) - 273.15
        With Emissivity (E): S_obj = (raw - (1-E)*S_refl) / E
        """
        
        # Constants
        R1 = self.config["PlanckR1"]
        B = self.config["PlanckB"]
        F = self.config["PlanckF"]
        O = self.config["PlanckO"]
        E = self.config["Emissivity"]
        T_refl = self.config["ReflectedApparentTemperature"]
        
        # Determine raw reflected component (reverse Planck)
        # For simplicity in this v1, we assume raw counts are proportional to radiance
        # and apply simple Planck. Thorough calibration requires reversing the formula for T_refl.
        
        # Simple Planck conversion
        # T = B / log(R1/(raw-O) + F) - 273.15
        
        # Mask invalid values to avoid log errors
        safe_raw = np.array(raw_counts, dtype=np.float32)
        
        # Handle scalar vs array
        if np.ndim(safe_raw) == 0:
            if safe_raw <= O:
                safe_raw = O + 1.0
        else:
            safe_raw[safe_raw <= O] = O + 1.0 # Avoid division by zero/log errors
        
        # Calculate Temp
        # Formula: T = B / log(R1 / (raw - O) + F) - 273.15
        
        denom = safe_raw - O
        # Avoid zero division
        if np.ndim(safe_raw) > 0:
            denom[denom == 0] = 1.0
        elif denom == 0:
            denom = 1.0
            
        val = (R1 / denom) + F
        
        # Avoid log of non-positive
        if np.ndim(safe_raw) > 0:
            val[val <= 0] = 1.0
        elif val <= 0:
            val = 1.0
            
        temp_k = B / np.log(val)
        temp_c = temp_k - 273.15
        
        return temp_c
