# noinspection PyPep8Naming
import multiprocessing
import shlex  # Use shlex.split to handle quoted strings
import sys
import time
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import Any

import PySimpleGUI as sg  # type: ignore[import-untyped]

from gigui import _logging, shared
from gigui._logging import set_logging_level_from_verbosity
from gigui.args_settings import Args, Settings, SettingsFile
from gigui.constants import AVAILABLE_FORMATS, DEBUG_SHOW_MAIN_EVENT_LOOP
from gigui.gi_runner import run_repos
from gigui.gui.psg_support import (
    GUIState,
    WindowButtons,
    disable_element,
    enable_element,
    help_window,
    log,
    popup,
    process_input_fstrs,
    process_inputs,
    process_n_files,
    update_col_percent,
    update_column_height,
    update_outfile_str,
    update_settings_file_str,
    window_state_from_settings,
)
from gigui.gui.psg_window import make_window
from gigui.keys import Keys
from gigui.tiphelp import Help, Tip
from gigui.utils import to_posix_fstr

logger = getLogger(__name__)

tip = Tip()
keys = Keys()


def run_gui(settings: Settings) -> None:
    recreate_window: bool = True

    # Create variable state, which is properly initialized via a call of
    # window_state_from_settings(...)
    state: GUIState = GUIState(
        settings.col_percent,
        settings.gui_settings_full_path,
        settings.multithread,
    )

    while recreate_window:
        recreate_window = run_inner(settings, state)
        set_logging_level_from_verbosity(settings.verbosity)


# pylint: disable=too-many-locals disable=too-many-branches disable=too-many-statements
def run_inner(settings: Settings, state: GUIState) -> bool:
    logger.debug(f"{settings = }")  # type: ignore

    shared.gui = True

    # Is set to True when handling "Reset settings file" menu item
    recreate_window: bool = False

    if sys.platform == "darwin":
        sg.set_options(font=("Any", 12))

    window: sg.Window
    window = make_window()
    shared.gui_window = window

    buttons = WindowButtons(window)
    buttons.configure_for_idle()

    window_state_from_settings(window, settings)  # type: ignore
    last_window_height: int = window.Size[1]  # type: ignore

    while True:
        event, values = window.read()  # type: ignore
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
                window_height: int = window.Size[1]  # type: ignore
                if window_height == last_window_height:
                    continue
                config_column: sg.Column = window[keys.config_column]  # type: ignore
                update_column_height(
                    config_column, window_height, last_window_height, state
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
                update_col_percent(window, last_window_height, values[event], state)  # type: ignore

            case keys.run:
                # Update processing of input patterns because dir state may have changed
                process_inputs(state, window)  # type: ignore
                if settings.multicore:
                    state.manager = multiprocessing.Manager()
                    state.stop_all_event = state.manager.Event()
                run(window, values, state, buttons)

            case keys.enable_stop_button:
                buttons.enable_stop_button()

            case keys.stop:
                state.stop_all_event.set()

            case keys.clear:
                window[keys.multiline].update(value="")  # type: ignore

            case keys.help:
                help_window()

            case keys.about:
                log(Help.about_info)

            # Window closed, or Exit button clicked
            case sg.WIN_CLOSED | keys.exit:
                break

            # Run command has finished via window.perform_long_operation in
            # run_gitinspector().
            case keys.end:
                buttons.configure_for_idle()

            # IO configuration
            ##################################

            case keys.input_fstrs:
                process_input_fstrs(values[event], state, window)

            case keys.outfile_base:
                update_outfile_str(state, window)

            case event if event in (keys.postfix, keys.prefix, keys.nofix):
                state.fix = event
                update_outfile_str(state, window)

            case keys.subfolder:
                state.subfolder = to_posix_fstr(values[event])
                process_inputs(state, window)

            case keys.n_files:
                process_n_files(values[keys.n_files], window[event])  # type: ignore

            # Output generation and formatting
            ##################################

            case keys.blame_history:
                value = values[event]
                match value:
                    case "none":
                        enable_element(window[keys.view])  # type: ignore
                        enable_element(window[keys.html])  # type: ignore
                        enable_element(window[keys.excel])  # type: ignore

                    case "dynamic":
                        window[keys.view].update(value=True)  # type: ignore
                        window[keys.html].update(value=False)  # type: ignore
                        window[keys.excel].update(value=False)  # type: ignore
                        disable_element(window[keys.view])  # type: ignore
                        disable_element(window[keys.html])  # type: ignore
                        disable_element(window[keys.excel])  # type: ignore

                    case "static":
                        window[keys.html].update(value=True)  # type: ignore
                        window[keys.excel].update(value=False)  # type: ignore
                        enable_element(window[keys.view])  # type: ignore
                        disable_element(window[keys.html])  # type: ignore
                        disable_element(window[keys.excel])  # type: ignore

            case keys.verbosity:
                set_logging_level_from_verbosity(values[event])

            # Settings
            ##################################

            case keys.save:
                settings.from_values_dict(values)
                settings.gui_settings_full_path = state.gui_settings_full_path
                settings.save()
                log("Settings saved to " + SettingsFile.get_settings_file())

            case keys.save_as:
                settings.from_values_dict(values)
                settings.gui_settings_full_path = state.gui_settings_full_path
                destination = values[keys.save_as]
                settings.save_as(destination)
                update_settings_file_str(state.gui_settings_full_path, window)
                log(f"Settings saved to {str(SettingsFile.get_location_path())}")

            case keys.load:
                settings_file = values[keys.load]
                settings_folder = str(Path(settings_file).parent)
                settings.load_safe_from(settings_file)
                SettingsFile.set_location(settings_file)
                window[keys.load].InitialFolder = settings_folder  # type: ignore
                window_state_from_settings(window, settings)
                update_settings_file_str(state.gui_settings_full_path, window)
                log(f"Settings loaded from {settings_file}")

            case keys.reset:
                settings.reset()
                window.close()
                recreate_window = True
                break  # strangely enough also works without the break

            case keys.reset_file:
                SettingsFile.reset()
                window.close()
                recreate_window = True
                break  # strangely enough also works without the break

            case keys.toggle_settings_file:
                state.gui_settings_full_path = not state.gui_settings_full_path
                if state.gui_settings_full_path:
                    update_settings_file_str(True, window)
                else:
                    update_settings_file_str(False, window)

    return recreate_window


def run(  # pylint: disable=too-many-branches
    window: sg.Window,
    values: dict,
    state: GUIState,
    buttons: WindowButtons,
) -> None:

    start_time = time.time()
    logger.debug(f"{values = }")  # type: ignore

    if state.input_patterns and not state.input_fstr_matches:
        popup("Error", "Input folder path invalid")
        return

    if not state.input_patterns:
        popup("Error", "Input folder path empty")
        return

    if not state.outfile_base:
        popup("Error", "Output file base empty")
        return

    if not state.subfolder_valid:
        popup(
            "Error",
            "Subfolder invalid: should be empty or a folder that exists in the "
            '"Input folder path"',
        )
        return

    args = Args()
    settings_schema: dict[str, Any] = SettingsFile.SETTINGS_SCHEMA["properties"]
    for key, value in settings_schema.items():
        if key not in {
            keys.profile,
            keys.fix,
            keys.n_files,
            keys.formats,
            keys.since,
            keys.until,
            keys.multithread,
            keys.gui_settings_full_path,
        }:
            if value["type"] == "array":
                setattr(args, key, shlex.split(values[key]))  # type: ignore
            else:
                setattr(args, key, values[key])

    args.multithread = state.multithread

    if values[keys.prefix]:
        args.fix = keys.prefix
    elif values[keys.postfix]:
        args.fix = keys.postfix
    else:
        args.fix = keys.nofix

    args.n_files = 0 if not values[keys.n_files] else int(values[keys.n_files])

    formats = []
    for key in AVAILABLE_FORMATS:
        if values[key]:
            formats.append(key)
    args.formats = formats

    buttons.disable_buttons(args.formats)

    for key in keys.since, keys.until:
        val = values[key]
        if not val or val == "":
            continue
        try:
            val = datetime.strptime(values[key], "%Y-%m-%d").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            popup(
                "Reminder",
                "Invalid date format. Correct format is YYYY-MM-DD. Please try again.",
            )
            return
        setattr(args, key, str(val))

    logger.debug(f"{args = }")  # type: ignore
    window.perform_long_operation(
        lambda: run_repos(args, start_time, state.manager, state.stop_all_event),
        keys.end,
    )


if __name__ == "__main__":
    current_settings: Settings
    error: str
    current_settings, error = SettingsFile.load()
    multiprocessing.freeze_support()
    _logging.ini_for_gui_base()
    run_gui(current_settings)
