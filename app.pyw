import os
import sched, time
import requests
import sys
import socket
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

ip_address = 'https://www.dash.instasck.com'
wait_newuser_tt = os.path.join(os.path.dirname(os.getcwd()), 'updater', 'wait_newuser_tt')
wait_newuser_ig = os.path.join(os.path.dirname(os.getcwd()), 'updater', 'wait_newuser_ig')

class ScreenShotsInterval:

    def __init__(self):
        self.save_ss_dir = "shots"
        if not os.path.exists(self.save_ss_dir):
            os.makedirs(self.save_ss_dir)
        # Variable to store the time of the last screenshot
        self.last_screenshot_time = None

        # Set the interval for screenshots (1 hour)
        self.screenshot_interval = timedelta(minutes=5)
    
    def delete_old_screenshots(self):
        """Delete screenshots older than 30 days."""
        now = datetime.now()
        days_threshold = 30

        for filename in os.listdir(self.save_ss_dir):
            file_path = os.path.join(self.save_ss_dir, filename)
            # Check if it's a file and ends with .png (assuming screenshots are in PNG format)
            if os.path.isfile(file_path) and filename.endswith(".png"):
                # Get the file's last modification time
                file_modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                # Calculate the age of the file
                file_age = now - file_modified_time
                # If the file is older than the threshold, delete it
                if file_age > timedelta(days=days_threshold):
                    os.remove(file_path)
                    print(f"Deleted old screenshot: {filename}")

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
        self.my_screenshot = ScreenShotsInterval()

    @classmethod
    def on_press(self, key):
        """
        GET KEYBOARD PRESSED KEYS
        """
        global last_key, last_x, last_y, file_name
        last_key = str(key)

    @classmethod
    def on_move(self, x, y):
        """
        GET MOVEMENT OF MOUSE
        """
        global last_key, last_x, last_y, file_name
        last_x, last_y = x, y

    @classmethod
    def on_click(self, x, y, button, pressed):
        """
        GET CLICK MOVEMENT MOUSE
        """
        if pressed:
            global last_key, last_x, last_y, file_name
            last_x, last_y = x+1 , y

    @classmethod
    def on_scroll(self, x, y, dx, dy):
        """
        GET MOVEMENT SCROLL
        """
        global last_key, last_x, last_y, file_name, ip_address
        last_x, last_y = x+1, y+1
    
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
        print(f'{datetime.now().strftime("%H:%M:%S")} ~ Set Status - {val} - to Cloud')
        url = f"{ip_address}/api/pc-module"
        data = {
            "pc_name": self.get_pc_name(),
            "status": val,
            "time": time,
            "list_of_phone": f'IG: {instagram_version_date()}, TT: {tiktok_version_date()}',
            # "list_of_phone": f'IG: 5, TT: 6',
        }
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
        tk.Tk.__init__(self)
        toolbar = tk.Frame(self)
        toolbar.pack(side="top", fill="x")
        # set window size
        self.geometry("500x200")
        self.title("Activity Monitor")
        self.text = tk.Text(self, wrap="word")
        self.text.pack(side="top", fill="both", expand=True)
        self.text.tag_configure("stderr", foreground="#b22222")
        self.text.yview("end")
        self.iconbitmap("activity.ico")
        sys.stdout = TextRedirector(self.text, "stdout")
        sys.stderr = TextRedirector(self.text, "stderr")

        self.protocol('WM_DELETE_WINDOW', self.on_close)

        self.run()

    def on_close(self):
        response = tkinter.messagebox.askyesno('Exit', 'Are you sure you want to exit?')
        if response:
            try:
                print('closing the scheduler')
                self.activity_obj.close()
                print('closing the listener')
                self.activity_obj.listener.stop()
                print('destroying the tk')
                self.quit()
            finally:
                sys.exit(0)

    def run(self):
        pc_name = get_input_pc_name()
        if pc_name == '':
            pc_name = get_hostname_pc()

        print(f'pc_name {pc_name}')
        self.activity_obj = UserActivity(pc_name)
        Thread(target=self.activity_obj._check_activity).start()
        Thread(target=self.activity_obj._check_timeactivity).start()


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
