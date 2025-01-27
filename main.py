import asyncio
import json
import os
import socket
import struct
import uuid
from settings import SettingsManager
import subprocess
import decky_plugin

settingsDir = os.environ["DECKY_PLUGIN_SETTINGS_DIR"]

CLIENT_ID = "1055680235682672682"

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

class EmptyReceiveException(Exception):
    """Raised when the socket was expected data but did not receive any"""

class HandshakeException(Exception):
    """Raised when the handshake fails"""

class Pipe:
    def get_ipc_file():
        flatpak_root = "/run/user/1000/app/com.discordapp.Discord"
        other_root = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/1000"

        for i in range(10):
            path = os.path.join(flatpak_root, "discord-ipc-{}".format(i))
            if os.path.exists(path):
                return path
            path = os.path.join(other_root, "discord-ipc-{}".format(i))
            if os.path.exists(path):
                return path
        
        return None

    def __init__(self, app_id):
        decky_plugin.logger.info("Initializing pipe")
        self.app_id = app_id
        self.socket = socket.socket(socket.AF_UNIX)
        self.connected = True

        file_path = Pipe.get_ipc_file()
        if file_path is None:
            self.connected = False
        else:
            self.socket.connect(file_path)
            decky_plugin.logger.debug("Connected to %s", file_path)

    def disconnect(self):
        decky_plugin.logger.info("Disconnecting")
        self._send({}, OP_CLOSE)

        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()
        self.socket = None
        self.connected = False

    def handshake(self):
        decky_plugin.logger.info("Beginning handshake for app %s", self.app_id)
        self._send({'v': 1, 'client_id': self.app_id}, op=OP_HANDSHAKE)
        data = self._recv()

        try:
            if data['cmd'] == 'DISPATCH' and data['evt'] == 'READY':
                decky_plugin.logger.info("Connected")
                return True
            
            else:
                decky_plugin.logger.error("Handshake failed %s", data)
                raise HandshakeException()

        except KeyError:
            if data['code'] == 4000:
                decky_plugin.logger.error("Handshake failed %s", data)
                raise HandshakeException()

    def _recv(self):
        recv_data = self.socket.recv(1024)
        enc_header = recv_data[:8]
        dec_header = struct.unpack("<ii", enc_header)
        enc_data = recv_data[8:]

        output = json.loads(enc_data.decode('UTF-8'))
        
        decky_plugin.logger.info(output)
        return output
    
    def _send(self, payload, op=OP_FRAME):
        decky_plugin.logger.info(payload)

        payload = json.dumps(payload).encode('UTF-8')
        payload = struct.pack('<ii', op, len(payload)) + payload

        self.socket.send(payload)

class Plugin:

    _settings = None
    _setting_auto_start_discord = False

    async def debug(self, args):
        decky_plugin.logger.debug("Called with %s ", args)

    async def load_settings(self):
        decky_plugin.logger.info("loading settings : ")
        self._settings = SettingsManager(name="decky-steamdeck-discord-status",settings_directory=settingsDir)
        self._settings.read()
        self._setting_auto_start_discord = self._settings.getSetting("auto_start_discord", False)
        decky_plugin.logger.info("- auto_start_discord : %s", self._setting_auto_start_discord)

        # needed for initialization
        await self.save_settings(self)
        return

    async def save_settings(self):
        decky_plugin.logger.info("saving settings")
        decky_plugin.logger.info("- auto_start_discord : %s", self._setting_auto_start_discord)
        self._settings.setSetting("auto_start_discord", self._setting_auto_start_discord)
        return

    async def get_setting_auto_start_discord(self):
        return self._setting_auto_start_discord
    
    async def set_setting_auto_start_discord(self, value: bool):
        self._setting_auto_start_discord = value
        self.save_settings(self)

    async def launch_discord(self):
        decky_plugin.logger.info("Launching Discord")

        flatpak_env = dict(os.environ)
        flatpak_env.pop("LD_LIBRARY_PATH", None)
        flatpak_env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        flatpak_env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        flatpak_env["XDG_SESSION_TYPE"] = "wayland"
        flatpak_env["WAYLAND_DISPLAY"] = "wayland-0"
        flatpak_env["DISPLAY"] = ":0"

        proc = await asyncio.create_subprocess_shell(
            "flatpak run com.discordapp.Discord --start-minimized",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=flatpak_env
        )
        decky_plugin.logger.info("Launched Discord with PID %s", proc.pid)
        return await self.is_connected(self)

    async def clear_activity(self):
        if self.pipe is None:
            return False
        
        decky_plugin.logger.info("Clearing activity")

        data = {
            "cmd": "SET_ACTIVITY",
            "args": {
                "pid": os.getpid()
            },
            "nonce": str(uuid.uuid4())
        }

        self.pipe._send(data)
        self.pipe.disconnect()
        self.pipe = None

        return True

    async def update_activity(self, activity):
        #if self.pipe:
        #    decky_plugin.logger.info("Clearing old pipe")
        #    self.pipe.disconnect()
        #    self.pipe = None

        try:
            data = {
                "cmd": "SET_ACTIVITY",
                "args": {
                    "pid": os.getpid(),
                    "activity": {
                        "state": "on Steam Deck",
                        "assets": {
                            "large_image": activity["imageUrl"],
                            "small_image": "https://cdn.discordapp.com/app-assets/1055680235682672682/1056080943783354388.png"
                        },
                        "timestamps": {
                            "start": activity["startTime"]
                        }
                    },
                },
                "nonce": str(uuid.uuid4())
            }

            discord_id = CLIENT_ID

            if "discordId" in activity:
                discord_id = activity["discordId"]
            else:
                data["args"]["activity"]["details"] = "Playing {}".format(activity["details"]["name"])

            decky_plugin.logger.info("Updating activity: %s (%s)", activity["details"]["name"], discord_id)
            self.pipe = Pipe(discord_id)

            if self.pipe.connected:
                self.pipe.handshake()
                self.pipe._send(data)
                return True
            else:
                return False
        except Exception as e:
            decky_plugin.logger.error(e)
            return False
        
    def check_connection(self):
        pipe_file = Pipe.get_ipc_file()

        return pipe_file is not None

    async def is_connected(self):
        decky_plugin.logger.info("Checking connection status")
        connected = False
        tries = 0

        while not connected and tries < 5:
            connected = self.check_connection(self)
            tries += 1
            
            if not connected:
                decky_plugin.logger.warning("No IPC file, retrying in 5 seconds")
                await asyncio.sleep(5)

        return connected
        
    async def disconnect(self):
        if self.pipe is not None and self.pipe.connected:
            decky_plugin.logger.info("Closing connection")
            self.pipe.disconnect()
            self.pipe = None

    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        decky_plugin.logger.info("Starting Discord status plugin")
        await self.load_settings(self)
        if(self._setting_auto_start_discord):
            await self.launch_discord(self)
        await self.is_connected(self)

    
    # Function called first during the unload process, utilize this to handle your plugin being removed
    async def _unload(self):
        self.disconnect(self)
        await self.save_settings(self)