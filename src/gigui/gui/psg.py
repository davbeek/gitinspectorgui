# noinspection PyPep8Naming

import multiprocessing
import os
import sys
import time
from datetime import datetime
from logging import getLogger
from multiprocessing.managers import SyncManager
from pathlib import Path
from typing import Any

import PySimpleGUI as sg  # type: ignore

from gigui import _logging, shared
from gigui._logging import add_cli_handler, set_logging_level_from_verbosity
from gigui.args_settings import Args, Settings, SettingsFile
from gigui.constants import (
    AVAILABLE_FORMATS,
    DEBUG_SHOW_MAIN_EVENT_LOOP,
    MAX_COL_HEIGHT,
    WINDOW_HEIGHT_CORR,
)
from gigui.data import RunnerQueues, get_runner_queues
from gigui.gi_runner import start_gi_runner
from gigui.gui.psg_base import (
    PSGBase,
    disable_element,
    enable_element,
    help_window,
    log,
    popup,
)
from gigui.gui.psg_window import make_window
from gigui.keys import Keys
from gigui.tiphelp import Help, Tip
from gigui.utils import to_posix_fstr

logger = getLogger(__name__)

tip = Tip()
keys = Keys()


class PSGUI(PSGBase):
    def __init__(self, settings: Settings, queues: RunnerQueues):
        super().__init__(settings)
        self.queues: RunnerQueues = queues

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

        add_cli_handler()
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

                    # Custom logging for GUI, see gigui._logging.GUIOutputHandler.emit
                case keys.logging:
                    message, color = values[event]
                    sg.cprint(message, text_color=color)

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
                    self.run(values)

                # Run command has finished via self.window.perform_long_operation in
                # run_gitinspector().
                case keys.end:
                    self.enable_buttons()

                case keys.clear:
                    self.window[keys.multiline].update(value="")  # type: ignore

                case keys.help:
                    help_window()

                case keys.about:
                    log(Help.about_info)

                # Window closed, or Exit button clicked
                case sg.WIN_CLOSED | keys.exit:
                    break

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

                case keys.blame_history:
                    value = values[event]
                    match value:
                        case "none":
                            enable_element(self.window[keys.view])  # type: ignore
                            enable_element(self.window[keys.html])  # type: ignore
                            enable_element(self.window[keys.excel])  # type: ignore

                        case "dynamic":
                            self.window[keys.view].update(value=True)  # type: ignore
                            self.window[keys.html].update(value=False)  # type: ignore
                            self.window[keys.excel].update(value=False)  # type: ignore
                            disable_element(self.window[keys.view])  # type: ignore
                            disable_element(self.window[keys.html])  # type: ignore
                            disable_element(self.window[keys.excel])  # type: ignore

                        case "static":
                            self.window[keys.html].update(value=True)  # type: ignore
                            self.window[keys.excel].update(value=False)  # type: ignore
                            enable_element(self.window[keys.view])  # type: ignore
                            disable_element(self.window[keys.html])  # type: ignore
                            disable_element(self.window[keys.excel])  # type: ignore

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

        args = Args()
        settings_schema: dict[str, Any] = SettingsFile.SETTINGS_SCHEMA["properties"]
        for schema_key, schema_value in settings_schema.items():
            if schema_key not in {
                keys.profile,
                keys.fix,
                keys.n_files,
                keys.formats,
                keys.since,
                keys.until,
                keys.multithread,
                keys.gui_settings_full_path,
            }:
                if schema_value["type"] == "array":
                    setattr(args, schema_key, values[schema_key].split(","))  # type: ignore
                else:
                    setattr(args, schema_key, values[schema_key])

        args.multithread = self.multithread

        if values[keys.prefix]:
            args.fix = keys.prefix
        elif values[keys.postfix]:
            args.fix = keys.postfix
        else:
            args.fix = keys.nofix

        args.n_files = 0 if not values[keys.n_files] else int(values[keys.n_files])

        formats = []
        for schema_key in AVAILABLE_FORMATS:
            if values[schema_key]:
                formats.append(schema_key)
        args.formats = formats

        self.disable_buttons()

        for schema_key in keys.since, keys.until:
            val = values[schema_key]
            if not val or val == "":
                continue
            try:
                val = datetime.strptime(values[schema_key], "%Y-%m-%d").strftime(
                    "%Y-%m-%d"
                )
            except (TypeError, ValueError):
                popup(
                    "Reminder",
                    "Invalid date format. Correct format is YYYY-MM-DD. Please try again.",
                )
                return
            setattr(args, schema_key, str(val))

        args.normalize()

        logger.debug(f"{args = }")  # type: ignore
        self.window.perform_long_operation(
            lambda: start_gi_runner(
                args,
                start_time,
                self.queues,
            ),
            keys.end,
        )

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


if __name__ == "__main__":
    settings: Settings
    error: str
    try:
        manager: SyncManager | None
        queues: RunnerQueues

        settings, error = SettingsFile.load()
        multiprocessing.freeze_support()
        _logging.ini_for_gui_base()

        queues, manager = get_runner_queues(settings.multicore)
        PSGUI(settings, queues)

        # Cleanup resources
        if queues.host_port:
            # Need to remove the last port value to avoid a deadlock
            queues.host_port.get()

        if manager:
            manager.shutdown()
    except KeyboardInterrupt:
        os._exit(0)
