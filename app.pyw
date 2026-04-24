import os
import sched, time
import requests
import sys
import socket
import pystray
from PIL import Image, ImageDraw
from PIL import ImageGrab
from threading import Thread
from pynput.keyboard import Listener as KeyboardListener
from pynput.mouse import Listener as MouseListener
from tendo import singleton
import tkinter as tk
import tkinter.messagebox
from datetime import datetime, timedelta
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import subprocess
import cv2
import numpy as np

# # locker
lock_filename = 'running.lock'
if os.path.exists(lock_filename):
    os.remove(lock_filename)
me = singleton.SingleInstance(lockfile=lock_filename)  # will sys.exit(-1) if other instance is running


last_key = ""
last_x = ""
last_y = ""
file_name = "data.json"

new_key, new_x, new_y = "","",""
last_update_time = datetime.now()
last_update_time_prev = datetime.min
update_active = False
offline_status = False
inactive_status = False
AWAY_TIME_SEC = 30
INACTIVE_TIME_SEC = 60
REFRESH_TRY_TIME_SEC = 2
MIN_CLOUD_UPDATE_TIME_SEC = 10

# Activity tracking
keyboard_counter = 0
mouse_counter = 0

class VideoRecorder:
    def __init__(self, pc_name):
        root_drive = os.path.splitdrive(os.getcwd())[0] + os.sep
        self.base_dir = os.path.join(root_drive, "activity", pc_name)
        self.save_dir = os.path.join(self.base_dir, "videos")
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.recording = False
        self.duration = 30
        self.break_time = 15
        self.fps = 5.0
        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')
        self.cleanup_days = 7

    def delete_old_videos(self):
        now = datetime.now()
        if not os.path.exists(self.save_dir):
            return
        for filename in os.listdir(self.save_dir):
            file_path = os.path.join(self.save_dir, filename)
            if os.path.isfile(file_path) and filename.endswith(".avi"):
                file_modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                if now - file_modified_time > timedelta(days=self.cleanup_days):
                    try:
                        os.remove(file_path)
                        print(f"Deleted old video: {filename}")
                    except:
                        pass

    def start_recording_loop(self):
        while True:
            self.record_segment()
            time.sleep(self.break_time)

    def record_segment(self):
        current_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(self.save_dir, f"video_{current_time_str}.avi")
        
        # Low quality: smaller resolution
        try:
            screen_size = ImageGrab.grab().size
        except:
            return # Probably locked or no screen
            
        low_res = (screen_size[0] // 2, screen_size[1] // 2)
        
        out = cv2.VideoWriter(filename, self.fourcc, self.fps, low_res)
        
        start_time = time.time()
        print(f"Recording video segment: {filename}")
        while (time.time() - start_time) < self.duration:
            img = ImageGrab.grab()
            img_np = np.array(img)
            frame = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            frame_small = cv2.resize(frame, low_res)
            out.write(frame_small)
            # Sleep to match FPS roughly
            time.sleep(1/self.fps)
        
        out.release()
        print(f"Finished recording: {filename}")

ip_address = 'https://www.dash.instasck.com'
wait_newuser_tt = os.path.join(os.path.dirname(os.getcwd()), 'updater', 'wait_newuser_tt')
wait_newuser_ig = os.path.join(os.path.dirname(os.getcwd()), 'updater', 'wait_newuser_ig')

class ScreenShotsInterval:

    def __init__(self, pc_name):
        root_drive = os.path.splitdrive(os.getcwd())[0] + os.sep
        self.base_dir = os.path.join(root_drive, "activity", pc_name)
        self.save_ss_dir = os.path.join(self.base_dir, "shots")
        if not os.path.exists(self.save_ss_dir):
            os.makedirs(self.save_ss_dir)
        # Variable to store the time of the last screenshot
        self.last_screenshot_time = None

        # Set the interval for screenshots (1 hour)
        self.screenshot_interval = timedelta(minutes=5)
    
    def delete_old_screenshots(self):
        """Delete screenshots and videos older than 7 days."""
        now = datetime.now()
        days_threshold = 7

        # Cleanup screenshots
        if os.path.exists(self.save_ss_dir):
            for filename in os.listdir(self.save_ss_dir):
                file_path = os.path.join(self.save_ss_dir, filename)
                if os.path.isfile(file_path) and filename.endswith(".png"):
                    file_modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if now - file_modified_time > timedelta(days=days_threshold):
                        try:
                            os.remove(file_path)
                            print(f"Deleted old screenshot: {filename}")
                        except:
                            pass
        
        # Cleanup videos
        video_dir = os.path.join(self.base_dir, "videos")
        if os.path.exists(video_dir):
            for filename in os.listdir(video_dir):
                file_path = os.path.join(video_dir, filename)
                if os.path.isfile(file_path) and filename.endswith(".avi"):
                    file_modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if now - file_modified_time > timedelta(days=days_threshold):
                        try:
                            os.remove(file_path)
                            print(f"Deleted old video: {filename}")
                        except:
                            pass

    def take_screenshot(self,):
        current_time = datetime.now()
        # If no screenshot has been taken yet, or the interval has passed since the last screenshot
        if self.last_screenshot_time is None or current_time - self.last_screenshot_time >= self.screenshot_interval:
            # Call the method to delete old screenshots
            self.delete_old_screenshots()
            # Get the current time and format it
            current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            try:
                screenshot = ImageGrab.grab()
                
                # Save screenshot
                screenshot.save(os.path.join(self.save_ss_dir, f"screenshot_{current_time}.png"))
                self.last_screenshot_time = datetime.now()
                print(f"Screenshot saved as screenshot_{current_time}.png")
            except:
                print('Failed taking screenshot')


class ActivityStatus:
    INACTIVE = 'inactive'
    ACTIVE = 'active'
    AWAY = 'away'


class UserActivity:

    def __init__(self, pc_name):
        self.pc_name_ext = pc_name
        self.sched_obj: sched.scheduler = None
        self.sched_obj_id = None
        self.listener = None
        self.my_screenshot = ScreenShotsInterval(pc_name)

    @classmethod
    def on_press(self, key):
        """
        GET KEYBOARD PRESSED KEYS
        """
        global last_key, last_x, last_y, file_name, keyboard_counter
        last_key = str(key)
        keyboard_counter += 1

    @classmethod
    def on_move(self, x, y):
        """
        GET MOVEMENT OF MOUSE
        """
        global last_key, last_x, last_y, file_name, mouse_counter
        last_x, last_y = x, y
        mouse_counter += 1

    @classmethod
    def on_click(self, x, y, button, pressed):
        """
        GET CLICK MOVEMENT MOUSE
        """
        if pressed:
            global last_key, last_x, last_y, file_name, mouse_counter
            last_x, last_y = x+1 , y
            mouse_counter += 5

    @classmethod
    def on_scroll(self, x, y, dx, dy):
        """
        GET MOVEMENT SCROLL
        """
        global last_key, last_x, last_y, file_name, ip_address, mouse_counter
        last_x, last_y = x+1, y+1
        mouse_counter += 2
    
    def get_pc_name(self,):
        pc_name = self.pc_name_ext
        if pc_name is None:
            try:
                pc_name = os.environ['USERDOMAIN']
            except:
                pass
            try:
                pc_name = os.environ['USER']
            except:
                pass
        
        return pc_name

    def __send_last_seen_to_web(self, val, time=None):
        global keyboard_counter, mouse_counter
        print(f'{datetime.now().strftime("%H:%M:%S")} ~ Set Status - {val} - to Cloud')
        
        # Calculate activity score
        raw_score = (keyboard_counter * 2) + mouse_counter
        # Normalize to 0-100. Max score around 300 for 10 seconds of high activity.
        activity_score = min(100, int((raw_score / 300) * 100))
        
        url = f"{ip_address}/api/pc-module"
        data = {
            "pc_name": self.get_pc_name(),
            "status": val,
            "time": time,
            "list_of_phone": f'Activity: {activity_score}',
        }

        # Reset counters
        keyboard_counter = 0
        mouse_counter = 0
        s = requests.Session()

        retries = Retry(total=50,
                        backoff_factor=0.1,
                        status_forcelist=[ 500, 502, 503, 504 ])
                        #allowed_methods=frozenset(['GET', 'POST']))

        s.mount('http://', HTTPAdapter(max_retries=retries))
        try:
            response = s.post(url, data=data, timeout=10)
            if response.status_code == 200:
                pass  
            else:
                print("__error__",response.__dict__)
        except:
            print('POST error')
            
        self.my_screenshot.take_screenshot()

    def _check_timeactivity(self):
        
        self.sched_obj = sched.scheduler(time.time, time.sleep)
        self.sched_obj_id = self.sched_obj.enter(REFRESH_TRY_TIME_SEC, 1, self.__time_schedular, (self.sched_obj,))
        self.sched_obj.run()

    def _check_activity(self):
        with MouseListener(on_click=UserActivity.on_click, on_move=UserActivity.on_move,on_scroll=UserActivity.on_scroll) as self.listener:
            with KeyboardListener(on_press=UserActivity.on_press) as self.listener:
                print("""Welcome\nRunning......................\n""")
                self.listener.join()

    def __time_schedular(self, sc):
        global new_key, new_x, new_y, last_update_time, last_update_time_prev, update_active, offline_status, inactive_status

        if (new_key != last_key) or (new_x != last_x) or (new_y != last_y):
            new_key = last_key
            new_x = last_x
            new_y = last_y

            if not update_active or \
                    datetime.now() > last_update_time_prev + timedelta(seconds=MIN_CLOUD_UPDATE_TIME_SEC):
                last_update_time_prev = last_update_time
                print(f'Last key press: {new_key} last mouse cord: ({new_x}, {new_y})')
                self.__send_last_seen_to_web(ActivityStatus.ACTIVE)
                update_active = True
                offline_status = False
                inactive_status = False
            #
            last_update_time = datetime.now()
        else:
            away_time = last_update_time + timedelta(seconds=AWAY_TIME_SEC)
            inactive_time = last_update_time + timedelta(seconds=INACTIVE_TIME_SEC)
            current_time = datetime.now()
            if current_time > away_time:
                if current_time > inactive_time:
                    if not inactive_status:
                        self.__send_last_seen_to_web(ActivityStatus.INACTIVE, last_update_time)
                        offline_status = False
                        update_active = False
                        inactive_status = True
                elif not offline_status:
                    self.__send_last_seen_to_web(ActivityStatus.AWAY, last_update_time)
                    offline_status = True
                    update_active = False
                    inactive_status = False
                else:
                    pass
        
        self.sched_obj_id = sc.enter(REFRESH_TRY_TIME_SEC, 1, self.__time_schedular, (sc,))
        
    def close(self):
        self.sched_obj.cancel(self.sched_obj_id)


class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str):
        self.widget.configure(state="normal")
        self.widget.insert("end", str, (self.tag,))
        self.widget.see(tk.END)
        self.widget.configure(state="disabled")


def get_hostname_pc():
    return socket.gethostname()


class TkApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.tray_icon = None
        self.tray_thread = None
        self.is_hidden = False

        toolbar = tk.Frame(self)
        toolbar.pack(side="top", fill="x")

        self.geometry("500x200")
        self.title("Activity Monitor")

        self.text = tk.Text(self, wrap="word")
        self.text.pack(side="top", fill="both", expand=True)
        self.text.tag_configure("stderr", foreground="#b22222")
        self.text.yview("end")

        try:
            self.iconbitmap("activity.ico")
        except Exception:
            pass

        sys.stdout = TextRedirector(self.text, "stdout")
        sys.stderr = TextRedirector(self.text, "stderr")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.create_tray_icon()
        self.withdraw()   # לא יופיע בהתחלה
        self.is_hidden = True

        self.run()

    def create_image(self):
        # אם יש לך PNG עדיף:
        # return Image.open("activity.png")

        try:
            return Image.open("activity.ico")
        except Exception:
            image = Image.new("RGB", (64, 64), (40, 40, 40))
            draw = ImageDraw.Draw(image)
            draw.rectangle((16, 16, 48, 48), fill=(0, 200, 0))
            return image

    def create_tray_icon(self):
        image = self.create_image()

        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show_window),
            pystray.MenuItem("Exit", self.exit_app)
        )

        self.tray_icon = pystray.Icon(
            "activity_monitor",
            image,
            "Activity Monitor",
            menu
        )

        self.tray_thread = Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def show_window(self, icon=None, item=None):
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify()
        self.is_hidden = False
        self.lift()
        self.focus_force()

    def hide_window(self):
        self.withdraw()
        self.is_hidden = True

    def on_close(self):
        # במקום לסגור - למזער ל-tray
        self.hide_window()

    def exit_app(self, icon=None, item=None):
        response = tkinter.messagebox.askyesno('Exit', 'Are you sure you want to exit?')
        if response:
            try:
                print('closing the scheduler')
                self.activity_obj.close()
            except Exception:
                pass

            try:
                print('closing the listener')
                if getattr(self.activity_obj, 'listener', None):
                    self.activity_obj.listener.stop()
            except Exception:
                pass

            try:
                if self.tray_icon:
                    self.tray_icon.stop()
            except Exception:
                pass

            try:
                print('destroying the tk')
                self.quit()
                self.destroy()
            finally:
                sys.exit(0)

    def run(self):
        pc_name = get_input_pc_name()
        if pc_name == '':
            import getpass
            username = getpass.getuser()
            hostname = get_hostname_pc()
            pc_name = f"{username}_{hostname}"

        print(f'pc_name {pc_name}')
        self.activity_obj = UserActivity(pc_name)
        self.video_recorder = VideoRecorder(pc_name)
        
        Thread(target=self.activity_obj._check_activity, daemon=True).start()
        Thread(target=self.activity_obj._check_timeactivity, daemon=True).start()
        Thread(target=self.video_recorder.start_recording_loop, daemon=True).start()
        
        # Auto-restart every 5 hours
        restart_interval_sec = 5 * 60 * 60
        Thread(target=self.schedule_restart, args=(restart_interval_sec,), daemon=True).start()

    def schedule_restart(self, delay):
        print(f"App will restart in {delay/3600} hours...")
        time.sleep(delay)
        self.restart_now()

    def restart_now(self):
        print("Restarting application...")
        try:
            # Clean up before restart
            if self.tray_icon:
                self.tray_icon.stop()
        except:
            pass
            
        # os.execv replaces the current process
        python = sys.executable
        os.execv(python, [python] + sys.argv)


def get_commit_day(repo_path):
    # Ensure that repo_path is a valid directory
    if not os.path.isdir(repo_path):
        return "Error: Invalid Git repository path"

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    # Run the git command to get the latest commit date from the specified repository path
    result = subprocess.run(
        ['git', '-C', repo_path, 'show', '-s', '--format=%ci'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        startupinfo = startupinfo,  #This suppresses the terminal window
        creationflags = subprocess.CREATE_NO_WINDOW  #Important for .pyw
    )

    if result.returncode == 0:
        # Extract just the day eg -25 from 2025-04-25 hh:mm:ss
        commit_date = result.stdout.strip()
        day = commit_date.split()[0] # Get day part from "YYYY-MM-DD"
        return day
    else:
        return f"Error: {result.stderr.strip()}"


def instagram_version_date():
    return get_commit_day(wait_newuser_ig)


def tiktok_version_date():
    return get_commit_day(wait_newuser_tt)


def get_input_pc_name():
    with open('inputs.txt') as f:
        try:
            first_line = f.readlines()[0]
        except:
            first_line = ''
        return first_line


if __name__ == '__main__':
    app = TkApp()
    app.mainloop()
