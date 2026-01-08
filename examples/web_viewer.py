from flask import Flask, Response, render_template, request, jsonify
import cv2
import numpy as np
import time
import os
from flir.thermal import ThermalContext
from flir.colormap import load_palette, PALETTE_DIR

app = Flask(__name__)

# Device Configuration
THERMAL_DEVICE = os.environ.get('FLIR_THERMAL_DEVICE', '/dev/video10')
VISIBLE_DEVICE = os.environ.get('FLIR_VISIBLE_DEVICE', '/dev/video11')
THERMAL_WIDTH, THERMAL_HEIGHT = 80, 60

# Global State
CURRENT_PALETTE_NAME = "Iron2"
CURRENT_PALETTE = load_palette(CURRENT_PALETTE_NAME)
SHOW_HOTSPOT = True
SHOW_COLDSPOT = True
MEASUREMENT_POINTS = [] # List of (x, y) tuples
EMISSIVITY = 0.95
REFLECTED_TEMP = 20.0

def get_available_palettes():
    palettes = []
    if os.path.exists(PALETTE_DIR):
        for f in os.listdir(PALETTE_DIR):
            if f.endswith('.raw'):
                palettes.append(f[:-4])
    return sorted(palettes)

def apply_colormap_16bit(frame_16, ctx):
    """Normalize 16-bit frame and apply colormap with radiometry"""
    # Create copy of context to apply current system params
    # We tweak the context object directly here for simplicity
    ctx.config["Emissivity"] = EMISSIVITY
    ctx.config["ReflectedApparentTemperature"] = REFLECTED_TEMP
    
    # Calculate temps
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(frame_16)
    center_val = frame_16[THERMAL_HEIGHT//2, THERMAL_WIDTH//2]
    
    min_temp = ctx.raw2temp(min_val)
    max_temp = ctx.raw2temp(max_val)
    center_temp = ctx.raw2temp(center_val)
    
    # Avoid divide by zero for normalization
    if max_val > min_val:
        norm = ((frame_16.astype(np.float32) - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
    else:
        norm = np.zeros_like(frame_16, dtype=np.uint8)
    
    # Apply palette (RGB)
    colored = CURRENT_PALETTE[norm]
    bgr = colored[:, :, ::-1].copy()
    
    # Upscale
    bgr = cv2.resize(bgr, (640, 480), interpolation=cv2.INTER_NEAREST)
    
    # Draw Info
    cv2.putText(bgr, f"Range: {min_temp:.1f}C - {max_temp:.1f}C", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(bgr, f"E:{EMISSIVITY:.2f}", (540, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    
    # Scale locations
    scale_x = 640 / THERMAL_WIDTH
    scale_y = 480 / THERMAL_HEIGHT
    
    # Draw User Measurements
    for (mx, my) in MEASUREMENT_POINTS:
        # User coords are in 640x480 space
        # Map back to 80x60 for temp lookup
        tx = int(mx / scale_x)
        ty = int(my / scale_y)
        
        # Clamp
        tx = max(0, min(THERMAL_WIDTH-1, tx))
        ty = max(0, min(THERMAL_HEIGHT-1, ty))
        
        raw_val = frame_16[ty, tx]
        temp = ctx.raw2temp(raw_val)
        
        cv2.drawMarker(bgr, (mx, my), (0, 255, 255), cv2.MARKER_CROSS, 20, 2)
        cv2.putText(bgr, f"{temp:.1f}C", (mx + 10, my - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    # Hot/Cold Spots
    if SHOW_HOTSPOT:
        hx = int(max_loc[0] * scale_x)
        hy = int(max_loc[1] * scale_y)
        cv2.circle(bgr, (hx, hy), 5, (0, 0, 255), 2)
        cv2.putText(bgr, f"{max_temp:.1f}C", (hx + 10, hy), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    if SHOW_COLDSPOT:
        lx = int(min_loc[0] * scale_x)
        ly = int(min_loc[1] * scale_y)
        cv2.circle(bgr, (lx, ly), 5, (255, 0, 0), 2)
        cv2.putText(bgr, f"{min_temp:.1f}C", (lx + 10, ly), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 100), 2)
    
    return bgr

# ... [Generator functions remain same] ...

@app.route('/')
def index():
    palettes = get_available_palettes()
    return render_template('index.html', 
                          palettes=palettes, 
                          current_palette=CURRENT_PALETTE_NAME, 
                          show_hot=SHOW_HOTSPOT, 
                          show_cold=SHOW_COLDSPOT,
                          emissivity=EMISSIVITY)

# ... [Video routes remain same] ...

@app.route('/api/set_params')
def set_params():
    global EMISSIVITY
    try:
        e = float(request.args.get('emissivity', EMISSIVITY))
        EMISSIVITY = max(0.1, min(1.0, e))
        return jsonify({"status": "ok", "emissivity": EMISSIVITY})
    except ValueError:
        return jsonify({"status": "error"}), 400

@app.route('/api/add_spot')
def add_spot():
    global MEASUREMENT_POINTS
    try:
        x = int(float(request.args.get('x')))
        y = int(float(request.args.get('y')))
        # Limit number of points
        if len(MEASUREMENT_POINTS) >= 5:
            MEASUREMENT_POINTS.pop(0)
        MEASUREMENT_POINTS.append((x, y))
        return jsonify({"status": "ok", "points": MEASUREMENT_POINTS})
    except:
        return jsonify({"status": "error"}), 400

@app.route('/api/clear_spots')
def clear_spots():
    global MEASUREMENT_POINTS
    MEASUREMENT_POINTS = []
    return jsonify({"status": "ok"})


def generate_thermal():
    cap = cv2.VideoCapture(THERMAL_DEVICE)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    # Try to set format, but it depends on the driver if this is needed or respected
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y','1','6',' '))
    
    # Initialize Radiometry
    ctx = ThermalContext()
    
    if not cap.isOpened():
        print("Could not open thermal device")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        
        # Handle 16-bit frame logic
        if frame.dtype == np.uint16:
             gray = frame.view(np.uint16)
        else:
             # Basic fallback check for 8-bit containers of 16-bit data
             if frame.shape[1] == THERMAL_WIDTH * 2:
                  gray = frame.view(np.uint16)
             else:
                  gray = frame
        
        # Reshape if needed
        if gray.shape != (THERMAL_HEIGHT, THERMAL_WIDTH):
             try:
                 gray = gray.reshape((THERMAL_HEIGHT, THERMAL_WIDTH))
             except:
                 pass

        final = apply_colormap_16bit(gray, ctx)
        ret, buffer = cv2.imencode('.jpg', final)
        frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# Singleton Video Reader
import threading

class VideoReader:
    def __init__(self, device_path):
        self.device_path = device_path
        self.lock = threading.Lock()
        self.frame_data = None
        self.running = False
        self.thread = None

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def _update(self):
        print(f"VideoReader started for {self.device_path}")
        fd = -1
        try:
            fd = os.open(self.device_path, os.O_RDONLY)
            while self.running:
                try:
                    # Read larger chunks to ensure full frame capture
                    # Standard MJPEG frames are <150KB
                    data = os.read(fd, 256 * 1024)
                    if data:
                        with self.lock:
                            self.frame_data = data
                    else:
                        time.sleep(0.01)
                except Exception as e:
                    print(f"Reader error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            print(f"Could not open device {self.device_path}: {e}")
        finally:
            if fd >= 0:
                os.close(fd)
        print("VideoReader stopped")

    def get_frame(self):
        with self.lock:
            return self.frame_data

# Initialize Global Reader
visible_reader = VideoReader(VISIBLE_DEVICE)
# Start strictly once? Or on first request? 
# Better on startup to ensure device is claimed correctly.
# But Flask reloader causes restart. We'll start in main block or lazy load.

def generate_visible():
    if not visible_reader.running:
        visible_reader.start()
        
    while True:
        frame = visible_reader.get_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.033) # Limit to ~30 FPS polling to save CPU

def generate_edges():
    if not visible_reader.running:
        visible_reader.start()

    while True:
        frame_bytes = visible_reader.get_frame()
        if frame_bytes is None:
            time.sleep(0.05)
            continue

        try:
            # Decode for processing
            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if frame is None:
                continue
                
            # HIGH-FIDELITY MSX ALGORITHM
            # 1. Convert to Grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 2. Blur to isolate low frequencies
            # Sigma=3.0 gives decent separation for objects
            blurred = cv2.GaussianBlur(gray, (0, 0), 3.0)
            
            # 3. Calculate High-Pass (Difference)
            # We want: (img - blur) -> centered at 127
            # cv2.addWeighted calculates: src1*alpha + src2*beta + gamma
            # gray * 1.0 + blurred * -1.0 + 127
            high_pass = cv2.addWeighted(gray, 2.0, blurred, -2.0, 127)
            
            # 4. Optional: Contrast stretch or clip?
            # The addWeighted with 2.0/-2.0 inherently boosts signal.
            
            # 5. Encode
            ret, buffer = cv2.imencode('.jpg', high_pass)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        except Exception as e:
            print(f"Edge processing error: {e}")
            
        time.sleep(0.05) # Cap MSX framerate to 20 FPS for performance




@app.route('/video_thermal')
def video_thermal():
    return Response(generate_thermal(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_visible')
def video_visible():
    return Response(generate_visible(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_edges')
def video_edges():
    return Response(generate_edges(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/set_palette')
def set_palette():
    global CURRENT_PALETTE, CURRENT_PALETTE_NAME
    name = request.args.get('name')
    if name:
        new_palette = load_palette(name)
        # Simple check if load_palette returned a valid array (it always returns something valid, even if fallback)
        CURRENT_PALETTE = new_palette
        CURRENT_PALETTE_NAME = name
        return jsonify({"status": "ok", "palette": name})
    return jsonify({"status": "error", "message": "No name provided"}), 400

@app.route('/api/toggle_spot')
def toggle_spot():
    global SHOW_HOTSPOT, SHOW_COLDSPOT
    spot_type = request.args.get('type')
    state = request.args.get('state') == 'true'
    
    if spot_type == 'hot':
        SHOW_HOTSPOT = state
    elif spot_type == 'cold':
        SHOW_COLDSPOT = state
    else:
        return jsonify({"status": "error", "message": "Invalid type"}), 400
        
    return jsonify({"status": "ok", "type": spot_type, "state": state})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
