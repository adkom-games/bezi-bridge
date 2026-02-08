import time
import os
from pywinauto import Application
import argparse
import sys
import json
import traceback
from PIL import Image, ImageChops
import numpy as np
from functools import wraps
import csv
import ctypes

# Constants for Windows Power Management
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# --- LOGGING & TIMING UTILITY ---
class PerformanceLogger:
    def __init__(self, console_debug=False):
        self.console_debug = console_debug  
        self.level = 0
        self.timings = [] 

    def log_entry(self, name):
        if self.console_debug:
            print(f"{'  ' * self.level}Entering {name}", file=sys.stderr, flush=True)
        self.level += 1

    def log_exit(self, name, duration):
        self.level -= 1
        if self.console_debug:
            print(f"{'  ' * self.level}Exiting {name} ({duration:.4f}s)", file=sys.stderr, flush=True)
        
        self.timings.append({
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'function': name, 
            'duration': round(duration, 6)
        })

    def save_timings(self):
        if self.timings:
            file_exists = os.path.exists("debug_timings.csv")
            try:
                with open("debug_timings.csv", "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=['timestamp', 'function', 'duration'])
                    if not file_exists:
                        writer.writeheader()
                    writer.writerows(self.timings)
                print(f"Performance timings saved to debug_timings.csv", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"Failed to save timings: {e}", file=sys.stderr, flush=True)

perf_logger = PerformanceLogger()

def debug_trace(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        perf_logger.log_entry(func.__name__)
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            duration = time.perf_counter() - start
            perf_logger.log_exit(func.__name__, duration)
    return wrapper

class BeziBridge:
    @debug_trace
    def __init__(self):
        self.config_file = "bezi_bridge.json"
        self.bezi_prompt = ""
        self.bezi_path = ""
        self.args = None
        self.config = None
        self.bezi_window = None

        try:
            self.ready_icon_inactive = Image.open("ref_ready.png").convert('RGB')
            self.ready_icon_active = Image.open("ref_ready_active.png").convert('RGB')
            self.ready_icon_busy = Image.open("ref_busy.png").convert('RGB')
        except Exception as e:
            print(f"Error loading reference images: {e}", file=sys.stderr, flush=True)

        self.bezi_submit_btn_width = 56
        self.bezi_submit_btn_height = 56
    
    @debug_trace
    def set_keep_awake(self, keep_awake=True):
        if keep_awake:
            # Prevent sleep and display off
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        else:
            # Reset to default Windows behavior
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

    @debug_trace
    def find_windows(self):
        """Refreshes connection to Bezi window."""
        try:
            app = Application(backend="uia").connect(title="Bezi", class_name="Tauri Window", timeout=10)
            self.bezi_window = app.window(title="Bezi", class_name="Tauri Window")
        except Exception as e:
            print(f"Exception connection to Bezi app. {e}", file=sys.stderr, flush=True)
            print(f"Attempting to launch exe.", file=sys.stderr, flush=True)
            if not self.bezi_path:
                self.bezi_path = r"C:\Program Files\Bezi\Bezi.exe"
            app = Application(backend="uia").start(self.bezi_path)
            self.bezi_window = app.window(title="Bezi", class_name="Tauri Window")
        #self.bezi_window.wait("visible", timeout=60)

    @debug_trace
    def get_bezi_state(self):
        self.find_windows()
        button = self.find_submit_button()
        if not button:
            print("unable to find submit button", file=sys.stderr, flush=True)
            exit(1)
        state = self.get_button_state(button)
        return state
        
    @debug_trace
    def find_submit_button(self):
        all_descendants = self.bezi_window.descendants()
        for item in all_descendants:
            rect = item.rectangle()
            if rect.width() == self.bezi_submit_btn_width and rect.height() == self.bezi_submit_btn_height:
                return item
        return None

    @debug_trace
    def new_thread(self):
        """Triggers a new thread and refreshes handles to prevent stale elements."""
        self.bezi_window.set_focus()
        self.bezi_window.type_keys("^T")
        time.sleep(1)
        self.find_windows()
        self.close_dialogs()

    @debug_trace
    def send_prompt(self, message):        
        if not message: raise ValueError("Empty prompt")
        
        # Wait until the button icon is INACTIVE, anything else means that
        # the ai is busy.
        while "INACTIVE" != self.get_bezi_state():
            self.close_dialogs()
            time.sleep(1)
        self.close_dialogs()
            
        try:
            self.find_windows()            
            prompt_box = self.bezi_window.descendants(control_type="Edit")[-1]
            prompt_box.set_text(message)
            time.sleep(1)
            self.bezi_window.type_keys("{ENTER}")
            time.sleep(2)
        except Exception as e:
            print(f"unable to find prompt box: {e}", file=sys.stderr, flush=True)
            return False
        self.find_windows()
        
        # Again wait for the button icon to become INACTIVE.
        while "INACTIVE" != self.get_bezi_state():
            self.close_dialogs()
            time.sleep(1)
        self.close_dialogs()

        self.find_windows()
        elements = self.bezi_window.descendants(control_type="Text")
        return [e.window_text().strip() for e in elements]

    @debug_trace
    def close_dialogs(self):
        self.click_button_by_name("Continue")
        self.find_windows()
        self.click_button_by_name("Keep All")
        self.find_windows()

    @debug_trace
    def click_button_by_name(self, button_name):
        try:
            button = self.bezi_window.child_window(title=button_name, control_type="Button", timeout=5)
            if button:
                button.click_input()
                return True
        except:
            return False
        return False

    @debug_trace
    def validate_arguments(self):
        if self.args.init:
            self.config["initialized"] = True
            self.config["bezi_path"] = self.args.bezi_path or r"C:\Program Files\Bezi\Bezi.exe"
            self.bezi_path = self.config["bezi_path"]
            return True 

        self.bezi_path = self.args.bezi_path or self.config.get("bezi_path")
        if self.args.prompt and os.path.exists(self.args.prompt):
            with open(self.args.prompt, 'r', encoding='utf-8') as f:
                self.bezi_prompt = f.read()
        else:
            self.bezi_prompt = self.args.prompt
        return True

    @debug_trace
    def load_config(self):
        if os.path.exists(self.config_file) and os.path.getsize(self.config_file) > 0:
            with open(self.config_file, "r") as f:
                return json.load(f)
        return {"initialized": False, "bezi_path": None}

    @debug_trace
    def save_config(self, config):
        with open(self.config_file, "w") as f:
            json.dump(config, f)

    def parse_arguments(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("prompt", nargs='?', help="Prompt or file path")
        parser.add_argument("-b", "--bezi_path", help="Full path to Bezi.exe")
        parser.add_argument("-i", "--init", action="store_true", help="Init session")
        parser.add_argument("-d", "--debug", action="store_true", help="Enable console trace")
        self.args = parser.parse_args()
        return self.args

    @debug_trace
    def get_button_state(self, btn_wrapper):
        current_img = btn_wrapper.capture_as_image().convert('RGB')
        if self.images_match(self.ready_icon_busy, current_img, 0.90):
            return "BUSY"
        if self.images_match(self.ready_icon_inactive, current_img, 0.90):
            return "INACTIVE"
        if self.images_match(self.ready_icon_active, current_img, 0.90):
            return "READY"
        return "UNKNOWN"

    @debug_trace
    def images_match(self, img1, img2, threshold=0.95):
        try:
            i1, i2 = np.array(img1), np.array(img2)
            if i1.shape != i2.shape: return False
            matching = np.mean(i1 == i2)
            return matching > threshold
        except:
            return False

    @debug_trace
    def run(self):
        self.set_keep_awake(True)
        try:
            self.config = self.load_config()
            self.parse_arguments()
            self.find_windows()
            if not self.validate_arguments(): return (False, "Invalid Args")
            if self.args.init:
                self.save_config(self.config)
                return (True, "Initialization Complete")
            self.new_thread()
            result = self.send_prompt(self.bezi_prompt)
            return (True, result)
        finally:
            self.set_keep_awake(False)

if __name__ == "__main__":
    bridge = BeziBridge()
    args = bridge.parse_arguments()
    if args.debug:
        perf_logger.console_debug = True
    
    try:
        success, result = bridge.run()
        if success: 
            print(f"{result}", flush=True)
    finally:
        perf_logger.save_timings()