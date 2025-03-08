# noinspection PyPep8Naming

import multiprocessing
import sys
import threading
import time
from logging import getLogger
from multiprocessing.managers import SyncManager
from multiprocessing.synchronize import Event as multiprocessingEvent
from pathlib import Path
from queue import Queue

import PySimpleGUI as sg  # type: ignore

from gigui import _logging, shared
from gigui._logging import set_logging_level_from_verbosity
from gigui.args_settings import Args, Settings, SettingsFile
from gigui.constants import (
    DEBUG_SHOW_MAIN_EVENT_LOOP,
    MAX_COL_HEIGHT,
    WINDOW_HEIGHT_CORR,
)
from gigui.gi_runner import GIRunner
from gigui.gui.psg_base import PSGBase, help_window, log, popup
from gigui.gui.psg_window import make_window
from gigui.keys import Keys
from gigui.output.repo_html_server import HTMLServer, require_server
from gigui.queues_events import RunnerQueues, get_runner_queues
from gigui.tiphelp import Help, Tip
from gigui.utils import to_posix_fstr

logger = getLogger(__name__)

tip = Tip()
keys = Keys()


class PSGUI(PSGBase):
    def __init__(
        self,
        settings: Settings,  # pylint: disable=redefined-outer-name
    ) -> None:
        super().__init__(settings)

        # THe following 5 vars are defined when the event keys.run is triggered
        self.queues: RunnerQueues
        self.manager: SyncManager | None = None
        self.logging_queue: Queue
        self.gi_runner_thread: threading.Thread | None = None
        self.html_server: HTMLServer = HTMLServer()

        self.recreate_window: bool = True

        while self.recreate_window:
            self.recreate_window = self.run_inner()
            set_logging_level_from_verbosity(self.settings.verbosity)

    # pylint: disable=too-many-locals disable=too-many-branches disable=too-many-statements
    def run_inner(self) -> bool:
        logger.debug(f"{self.settings = }")  # type: ignore

        shared.gui = True

        # Is set to True when handling "Reset settings file" menu item
        recreate_window: bool = False

        if sys.platform == "darwin":
            sg.set_options(font=("Any", 12))

        self.window = make_window()
        shared.gui_window = self.window

        self.enable_buttons()

        self.window_state_from_settings()  # type: ignore
        last_window_height: int = self.window.Size[1]  # type: ignore

        while True:
            event, values = self.window.read()  # type: ignore
            if DEBUG_SHOW_MAIN_EVENT_LOOP and (
                # ignore event generated by logger to prevent infinite loop
                not (event == keys.logging)
            ):
                if event in values.keys():
                    value = values[event]
                    logger.debug(
                        # display event, its value, type of value and all values
                        f"EVENT LOOP\n{event = },  {value = },  {type(value) = }\nvalues =\n{values}"
                    )
                else:
                    # display event and all values
                    logger.debug(f"EVENT LOOP\n{event = }\nvalues = \n{values}")
            match event:
                case "Conf":
                    window_height: int = self.window.Size[1]  # type: ignore
                    if window_height == last_window_height:
                        continue
                    config_column: sg.Column = self.window[keys.config_column]  # type: ignore
                    self._update_column_height(
                        config_column,
                        window_height,
                        last_window_height,
                        self.col_percent,
                    )
                    last_window_height = window_height

                # Custom logging for GUI, see gigui._logging.GUIOutputHandler.emit()
                case keys.logging:
                    message, color = values[event]
                    sg.cprint(message, text_color=color)

                # Custom logging for GUI, see gigui._logging.log
                case keys.log:
                    message, color = values[event]
                    sg.cprint(message, text_color=color, end="")

                # Top level buttons
                ###########################
                case keys.col_percent:
                    self._update_col_percent(last_window_height, values[event])  # type: ignore

                case keys.run:
                    # Update processing of input patterns because dir state may have changed
                    self.process_inputs()  # type: ignore
                    self.queues, self.logging_queue, self.manager = get_runner_queues(
                        self.settings.multicore
                    )
                    self.run(values)

                # Run command has finished
                case keys.end:
                    if self.gi_runner_thread:
                        self.gi_runner_thread.join()
                        if self.manager:
                            self.manager.shutdown()
                    self.gi_runner_thread = None
                    self.enable_buttons()

                case keys.clear:
                    self.window[keys.multiline].update(value="")  # type: ignore

                case keys.help:
                    help_window()

                case keys.about:
                    log(Help.about_info)

                # Exit button clicked
                case keys.exit:
                    self.close()
                    return False

                # Window closed
                case sg.WIN_CLOSED:
                    self.close()
                    return False

                # IO configuration
                ##################################
                case keys.input_fstrs:
                    self.process_input_fstrs(values[event])

                case keys.outfile_base:
                    self.update_outfile_str()

                case event if event in (keys.postfix, keys.prefix, keys.nofix):
                    self.fix = event
                    self.update_outfile_str()

                case keys.subfolder:
                    self.subfolder = to_posix_fstr(values[event])
                    self.process_inputs()

                case keys.n_files:
                    self.process_n_files(values[keys.n_files], self.window[event])  # type: ignore

                # Output generation and formatting
                ##################################
                case keys.auto:
                    self.process_view_format_radio_buttons(event)

                case keys.dynamic_blame_history:
                    self.process_view_format_radio_buttons(event)

                case keys.html:
                    self.process_view_format_radio_buttons(event)

                case keys.excel:
                    self.process_view_format_radio_buttons(event)

                case keys.verbosity:
                    set_logging_level_from_verbosity(values[event])

                # Settings
                ##################################
                case keys.save:
                    self.settings.from_values_dict(values)
                    self.settings.gui_settings_full_path = self.gui_settings_full_path
                    self.settings.save()
                    log("Settings saved to " + SettingsFile.get_settings_file())

                case keys.save_as:
                    self.settings.from_values_dict(values)
                    self.settings.gui_settings_full_path = self.gui_settings_full_path
                    destination = values[keys.save_as]
                    self.settings.save_as(destination)
                    self.update_settings_file_str(self.gui_settings_full_path)
                    log(f"Settings saved to {str(SettingsFile.get_location_path())}")

                case keys.load:
                    settings_file = values[keys.load]
                    settings_folder = str(Path(settings_file).parent)
                    self.settings.load_safe_from(settings_file)
                    SettingsFile.set_location(settings_file)
                    self.window[keys.load].InitialFolder = settings_folder  # type: ignore
                    self.window_state_from_settings()
                    self.update_settings_file_str(self.gui_settings_full_path)
                    log(f"Settings loaded from {settings_file}")

                case keys.reset:
                    self.settings.reset()
                    self.window.close()
                    recreate_window = True
                    break  # strangely enough also works without the break

                case keys.reset_file:
                    SettingsFile.reset()
                    self.window.close()
                    recreate_window = True
                    break  # strangely enough also works without the break

                case keys.toggle_settings_file:
                    self.gui_settings_full_path = not self.gui_settings_full_path
                    if self.gui_settings_full_path:
                        self.update_settings_file_str(True)
                    else:
                        self.update_settings_file_str(False)

        return recreate_window

    def run(  # pylint: disable=too-many-branches
        self,
        values: dict,
    ) -> None:
        start_time = time.time()
        logger.debug(f"{values = }")  # type: ignore

        if self.input_fstrs and not self.input_fstr_matches:
            popup("Error", "Input folder path invalid")
            return
        if not self.input_fstrs:
            popup("Error", "Input folder path empty")
            return
        if not self.outfile_base:
            popup("Error", "Output file base empty")
            return
        if not self.subfolder_valid:
            popup(
                "Error",
                "Subfolder invalid: should be empty or a folder that exists in the "
                '"Input folder path"',
            )
            return

        self.set_args(values)
        self.disable_buttons()
        self.queues, self.logging_queue, self.manager = get_runner_queues(
            self.args.multicore
        )
        logger.debug(f"{self.args = }")  # type: ignore

        if require_server(self.args):
            if not self.html_server:
                self.html_server = HTMLServer()
            self.html_server.set_args(self.args)

        self.gi_runner_thread = threading.Thread(
            target=self.start_gi_runner,
            args=(
                self.args,
                start_time,
                self.queues,
                self.logging_queue,
                multiprocessing.Event() if self.args.multicore else threading.Event(),
                self.html_server,
            ),
            name="GI Runner",
        )
        self.gi_runner_thread.start()

    def start_gi_runner(
        self,
        args: Args,
        start_time: float,
        queues: RunnerQueues,
        logging_queue: Queue,
        sync_event: multiprocessingEvent | threading.Event,
        html_server: HTMLServer | None = None,
    ) -> None:
        GIRunner(
            args,
            start_time,
            queues,
            logging_queue,
            sync_event,
            html_server,
        )
        if not shared.gui_window_closed:
            self.window.write_event_value(keys.end, None)

    def shutdown_html_server(self) -> None:
        if self.html_server.server:
            self.html_server.send_general_shutdown_request()
            self.html_server.events.server_shutdown_request.wait()
            self.html_server.server.shutdown()
            self.html_server.server.server_close()
            if (
                self.html_server.server_thread
                and self.html_server.server_thread.is_alive()
            ):
                self.html_server.server_thread.join()

    def close(self) -> None:
        self.shutdown_html_server()
        if self.gi_runner_thread:
            shared.gui_window_closed = True
            self.gi_runner_thread.join()
            if self.manager:
                self.manager.shutdown()

    def _update_column_height(
        self,
        element: sg.Element,
        window_height: int,
        last_window_height: int,
        col_percent: int,
    ) -> None:
        column_height = element.Widget.canvas.winfo_height()  # type: ignore
        if column_height < MAX_COL_HEIGHT or (window_height - last_window_height) <= 0:
            column_height = int(
                (window_height - WINDOW_HEIGHT_CORR) * col_percent / 100
            )
            column_height = min(column_height, MAX_COL_HEIGHT)
            element.Widget.canvas.configure({"height": column_height})  # type: ignore

    def _update_col_percent(self, window_height: int, percent: int) -> None:
        config_column: sg.Column = self.window[keys.config_column]  # type: ignore
        if self.col_percent != percent:
            self.col_percent = percent
            self._update_column_height(
                config_column, window_height, window_height, self.col_percent
            )


def main():
    settings: Settings
    settings, _ = SettingsFile.load()
    _logging.ini_for_gui_base()
    _logging.add_cli_handler()
    PSGUI(settings)


if __name__ == "__main__":
    # Required for pyinstaller to support the use of multiprocessing in gigui
    multiprocessing.freeze_support()
    main()
