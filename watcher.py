from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import subprocess
import time

class ReloadHandler(FileSystemEventHandler):
    def __init__(self, command):
        self.command = command
        self.process = self.start_process()

    def start_process(self):
        return subprocess.Popen(self.command, shell=True)

    def restart_process(self):
        print("Changes detected! Restarting the bot...")
        self.process.terminate()
        self.process = self.start_process()

    def on_modified(self, event):
        if event.src_path.endswith(".py"):  
            self.restart_process()

if __name__ == "__main__":
    path = "."
    command = "python3 bot.py"
    event_handler = ReloadHandler(command)
    observer = Observer()
    observer.schedule(event_handler, path=path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
