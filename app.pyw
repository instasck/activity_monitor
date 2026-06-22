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
import getpass

username = getpass.getuser()

lock_filename = f'running_{username}.lock'

if os.path.exists(lock_filename):
    os.remove(lock_filename)

me = singleton.SingleInstance(lockfile=lock_filename)


last_key = ""
last_x = ""
last_y = ""
file_name = "data.json"

# Activity tracking
keyboard_counter = 0
mouse_counter = 0
activity_events = []

new_key, new_x, new_y = "", "", ""
last_update_time = datetime.now()
last_update_time_prev = datetime.min
update_active = False
offline_status = False
inactive_status = False
AWAY_TIME_SEC = 30
INACTIVE_TIME_SEC = 60
REFRESH_TRY_TIME_SEC = 2
MIN_CLOUD_UPDATE_TIME_SEC = 10

ip_address = 'https://www.dash.instasck.com'
wait_newuser_tt = os.path.join(os.path.dirname(os.getcwd()), 'updater', 'wait_newuser_tt')
wait_newuser_ig = os.path.join(os.path.dirname(os.getcwd()), 'updater', 'wait_newuser_ig')


class VideoRecorder:
    def __init__(self, pc_name):
        root_drive = os.path.splitdrive(os.getcwd())[0] + os.sep
        self.base_dir = os.path.join(root_drive, "activity", pc_name)
        self.save_dir = os.path.join(self.base_dir, "shots")
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.recording = False
        self.duration = 15
        self.break_time = 45
        self.fps = 8.0
        self.fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        self.cleanup_hours = 48

    def delete_old_files(self):
        """Delete videos and screenshots older than 48 hours."""
        now = datetime.now()
        if not os.path.exists(self.save_dir):
            return
        for filename in os.listdir(self.save_dir):
            file_path = os.path.join(self.save_dir, filename)
            if os.path.isfile(file_path) and (filename.endswith(".avi") or filename.endswith(".png") or filename.endswith(".jpg")):
                file_modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                if now - file_modified_time > timedelta(hours=self.cleanup_hours):
                    try:
                        os.remove(file_path)
                        print(f"Deleted old file: {filename}")
                    except:
                        pass

    def start_recording_loop(self):
        while True:
            self.record_segment()
            time.sleep(self.break_time)

    def record_segment(self):
        current_time = datetime.now()
        global activity_events
        # Check if there was any activity in the last minute
        activity_in_interval = any(t > current_time - timedelta(minutes=1) for t in activity_events)
        
        # Cleanup old activity events
        cutoff = current_time - timedelta(minutes=5)
        activity_events = [t for t in activity_events if t > cutoff]

        if not activity_in_interval:
            print("No activity in last minute, skipping video recording.")
            return

        self.delete_old_files()
        current_time_str = current_time.strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(self.save_dir, f"video_{current_time_str}.avi")
        
        try:
            # Test ImageGrab to ensure it works
            img_test = ImageGrab.grab()
            screen_size = img_test.size
        except Exception as e:
            print(f"Failed to grab screen for video size: {e}")
            return # Probably locked or no screen
            
        full_res = (screen_size[0] // 2 * 2, screen_size[1] // 2 * 2)
        
        try:
            # MJPG is more compatible in headless environments
            out = cv2.VideoWriter(filename, self.fourcc, self.fps, full_res)
            
            if not out.isOpened():
                print(f"Failed to open VideoWriter with {filename}")
                return

            start_time = time.time()
            print(f"Recording video segment: {filename}")
            frames_recorded = 0
            while (time.time() - start_time) < self.duration:
                try:
                    img = ImageGrab.grab()
                    img_np = np.array(img)
                    frame = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                    frame_final = cv2.resize(frame, full_res)
                    out.write(frame_final)
                    frames_recorded += 1
                except Exception as e:
                    print(f"Error capturing frame: {e}")
                time.sleep(1/self.fps)
            
            out.release()
            print(f"Finished recording: {filename}. Frames recorded: {frames_recorded}")
        except Exception as e:
            print(f"Failed to record video: {e}")


class ScreenShotsInterval:

    def __init__(self, pc_name):
        self.last_screenshot_time = None
        root_drive = os.path.splitdrive(os.getcwd())[0] + os.sep
        self.base_dir = os.path.join(root_drive, "activity", pc_name)
        self.save_ss_dir = os.path.join(self.base_dir, "shots")
        if not os.path.exists(self.save_ss_dir):
            os.makedirs(self.save_ss_dir)

        # Set the interval for screenshots (10 seconds)
        self.screenshot_interval = timedelta(seconds=10)

    def take_screenshot(self, ):
        current_time = datetime.now()
        # If no screenshot has been taken yet, or the interval has passed since the last screenshot
        if self.last_screenshot_time is None or current_time - self.last_screenshot_time >= self.screenshot_interval:
            # Check for activity in the last interval
            global activity_events
            activity_in_interval = any(t > current_time - self.screenshot_interval for t in activity_events)
            if not activity_in_interval:
                return

            # Call the method to delete old files (done by VideoRecorder loop too, but here for safety)
            # Actually, VideoRecorder handles deletion for this folder now, so we can just focus on taking screenshot
            
            # Get the current time and format it
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            try:
                screenshot = ImageGrab.grab()

                # Standard quality: full resolution (ensuring even dimensions)
                width, height = screenshot.size
                full_res = (width // 2 * 2, height // 2 * 2)
                screenshot = screenshot.resize(full_res, Image.LANCZOS)

                # Convert to RGB if necessary for JPEG
                if screenshot.mode in ("RGBA", "P"):
                    screenshot = screenshot.convert("RGB")

                # Save screenshot as JPG with improved quality
                save_path = os.path.join(self.save_ss_dir, f"screenshot_{timestamp}.jpg")
                screenshot.save(save_path, "JPEG", quality=80)

                self.last_screenshot_time = datetime.now()
                print(f"Screenshot saved as screenshot_{timestamp}.jpg (standard quality)")
            except Exception as e:
                print(f'Failed taking screenshot: {e}')


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
        global last_key, last_x, last_y, file_name, keyboard_counter, activity_events
        last_key = str(key)
        keyboard_counter += 1
        activity_events.append(datetime.now())

    @classmethod
    def on_move(self, x, y):
        """
        GET MOVEMENT OF MOUSE
        """
        global last_key, last_x, last_y, file_name, mouse_counter, activity_events
        last_x, last_y = x, y
        mouse_counter += 1
        activity_events.append(datetime.now())

    @classmethod
    def on_click(self, x, y, button, pressed):
        """
        GET CLICK MOVEMENT MOUSE
        """
        if pressed:
            global last_key, last_x, last_y, file_name, mouse_counter, activity_events
            last_x, last_y = x + 1, y
            mouse_counter += 5
            activity_events.append(datetime.now())

    @classmethod
    def on_scroll(self, x, y, dx, dy):
        """
        GET MOVEMENT SCROLL
        """
        global last_key, last_x, last_y, file_name, ip_address, mouse_counter, activity_events
        last_x, last_y = x + 1, y + 1
        mouse_counter += 2
        activity_events.append(datetime.now())

    def get_pc_name(self, ):
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
        global keyboard_counter, mouse_counter, activity_events
        print(f'{datetime.now().strftime("%H:%M:%S")} ~ Set Status - {val} - to Cloud')
        
        # Calculate activity score based on the last 5 minutes
        now = datetime.now()
        five_minutes_ago = now - timedelta(minutes=5)
        # Keep events that could contribute to the last 5 minutes (up to 10s before the window)
        activity_threshold = five_minutes_ago - timedelta(seconds=10)
        
        # Filter events
        activity_events = [t for t in activity_events if t > activity_threshold]
        
        active_duration_seconds = 0
        if activity_events:
            # Sort events by timestamp
            sorted_events = sorted(activity_events)
            
            # Merge intervals of 10 seconds for each event
            # Each event at time 't' makes the user active for [t, t + 10s]
            merged_intervals = []
            if sorted_events:
                current_start = sorted_events[0]
                current_end = current_start + timedelta(seconds=10)
                
                for i in range(1, len(sorted_events)):
                    next_event = sorted_events[i]
                    if next_event <= current_end:
                        # Overlapping or adjacent, extend the current interval
                        current_end = max(current_end, next_event + timedelta(seconds=10))
                    else:
                        # No overlap, save current and start new
                        merged_intervals.append((current_start, current_end))
                        current_start = next_event
                        current_end = next_event + timedelta(seconds=10)
                merged_intervals.append((current_start, current_end))
            
            # Sum up durations, clipping to the 5-minute window
            total_active_timedelta = timedelta(0)
            for start, end in merged_intervals:
                actual_start = max(start, five_minutes_ago)
                actual_end = min(end, now)
                if actual_end > actual_start:
                    total_active_timedelta += (actual_end - actual_start)
            
            active_duration_seconds = total_active_timedelta.total_seconds()
        
        # Activity score is the percentage of active time in the 5-minute window (300 seconds)
        activity_score = min(100, int((active_duration_seconds / 300) * 100))
        
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
                        status_forcelist=[500, 502, 503, 504])
        # allowed_methods=frozenset(['GET', 'POST']))

        s.mount('http://', HTTPAdapter(max_retries=retries))
        try:
            response = s.post(url, data=data, timeout=10)
            if response.status_code == 200:
                pass
            else:
                print("__error__", response.__dict__)
        except:
            print('POST error')

        self.my_screenshot.take_screenshot()

    def _check_timeactivity(self):

        self.sched_obj = sched.scheduler(time.time, time.sleep)
        self.sched_obj_id = self.sched_obj.enter(REFRESH_TRY_TIME_SEC, 1, self.__time_schedular, (self.sched_obj,))
        self.sched_obj.run()

    def _check_activity(self):
        with MouseListener(on_click=UserActivity.on_click, on_move=UserActivity.on_move,
                           on_scroll=UserActivity.on_scroll) as self.listener:
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
                last_update_time_prev = datetime.now()
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
                    if not inactive_status or \
                            datetime.now() > last_update_time_prev + timedelta(seconds=60):
                        self.__send_last_seen_to_web(ActivityStatus.INACTIVE, last_update_time)
                        offline_status = False
                        update_active = False
                        inactive_status = True
                        last_update_time_prev = datetime.now()
                elif not offline_status or \
                        datetime.now() > last_update_time_prev + timedelta(seconds=60):
                    self.__send_last_seen_to_web(ActivityStatus.AWAY, last_update_time)
                    offline_status = True
                    update_active = False
                    inactive_status = False
                    last_update_time_prev = datetime.now()
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
        self.withdraw()  # לא יופיע בהתחלה
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
            pc_name = f"USER_{hostname}_{username}"

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
        #self.restart_now()

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
        startupinfo=startupinfo,  # This suppresses the terminal window
        creationflags=subprocess.CREATE_NO_WINDOW  # Important for .pyw
    )

    if result.returncode == 0:
        # Extract just the day eg -25 from 2025-04-25 hh:mm:ss
        commit_date = result.stdout.strip()
        day = commit_date.split()[0]  # Get day part from "YYYY-MM-DD"
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
