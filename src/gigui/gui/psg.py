# noinspection PyPep8Naming
import logging
import multiprocessing
import shlex  # Use shlex.split to handle quoted strings
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import PySimpleGUI as sg  # type: ignore[import-untyped]

from gigui import shared
from gigui._logging import set_logging_level_from_verbosity
from gigui.args_settings import Args, Settings, SettingsFile
from gigui.constants import AVAILABLE_FORMATS, DEBUG_SHOW_MAIN_EVENT_LOOP, DYNAMIC
from gigui.gitinspector import main as gitinspector_main
from gigui.gui.psg_support import (
    GUIState,
    WindowButtons,
    help_window,
    log,
    popup,
    popup_custom,
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
from gigui.utils import open_webview

logger = logging.getLogger(__name__)

tip = Tip()
keys = Keys()


def run(settings: Settings) -> None:
    recreate_window: bool = True
    while recreate_window:
        recreate_window = run_inner(settings)
        settings = Settings()
        set_logging_level_from_verbosity(settings.verbosity)


# pylint: disable=too-many-locals disable=too-many-branches disable=too-many-statements
def run_inner(settings: Settings) -> bool:
    logger.info(f"{settings = }")

    # Create variable state, which is properly initialized via a call of
    # window_state_from_settings(...)
    state: GUIState = GUIState(settings.col_percent, settings.gui_settings_full_path)
    shared.gui = True

    # Is set to True when handling "Reset settings file" menu item
    recreate_window: bool = False

    if sys.platform == "darwin":
        sg.set_options(font=("Any", 12))

    window: sg.Window
    window = make_window()
    shared.gui_window = window

    buttons = WindowButtons(window)

    window_state_from_settings(window, settings)  # type: ignore
    last_window_height: int = window.Size[1]  # type: ignore

    # Multicore not working and not implemented in GUI. No checkbox to enable it.
    # Ensure that multicore is False.
    settings.multi_core = False

    while True:
        event, values = window.read()  # type: ignore
        if DEBUG_SHOW_MAIN_EVENT_LOOP and (
            # ignore event generated by logger to prevent infinite loop
            not (event == keys.debug)
        ):
            if event in values.keys():
                value = values[event]
                logger.debug(
                    f"EVENT LOOP\n{event = },  {value = },  {type(value) = }\nvalues =\n{values}"
                )
            else:
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

            case keys.col_percent:
                update_col_percent(window, last_window_height, values[event], state)  # type: ignore

            case keys.execute:
                # Update processing of input patterns because dir state may have changed
                process_inputs(state, window)  # type: ignore
                execute(window, values, state)

            case keys.clear:
                window[keys.multiline].update(value="")  # type: ignore

            case keys.save:
                new_settings = Settings.from_values_dict(values)
                new_settings.gui_settings_full_path = state.gui_settings_full_path
                new_settings.save()
                log("Settings saved to " + SettingsFile.get_settings_file())

            case keys.save_as:
                destination = values[keys.save_as]
                new_settings = Settings.from_values_dict(values)
                new_settings.save_as(destination)
                update_settings_file_str(state.gui_settings_full_path, window)
                log(f"Settings saved to {str(SettingsFile.get_location())}")

            case keys.load:
                settings_file = values[keys.load]
                settings_folder = str(Path(settings_file).parent)
                new_settings, _ = SettingsFile.load_from(settings_file)
                SettingsFile.set_location(settings_file)
                window[keys.load].InitialFolder = settings_folder  # type: ignore
                window_state_from_settings(window, new_settings)
                update_settings_file_str(state.gui_settings_full_path, window)
                log(f"Settings loaded from {settings_file}")

            case keys.reset:
                res = popup_custom(
                    "Clear settings file",
                    "This will cause all settings to be reset to their default values. "
                    "Are you sure?",
                )
                if res == "OK":
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

            case keys.help:
                help_window()

            case keys.about:
                log(Help.about_info)

            # Window closed, or Exit button clicked
            case sg.WIN_CLOSED | keys.exit:
                break

            # Execute command has finished via window.perform_long_operation in
            # run_gitinspector().
            case keys.end:
                buttons.enable_all()

            case keys.log:
                message, end, color = values["log"]
                sg.cprint(message, end=end, text_color=color)

            # Custom logging for GUI, see gigui._logging.GUIOutputHandler.emit
            case keys.debug:
                message, color = values["debug"]
                sg.cprint(message, text_color=color)

            case keys.input_fstrs:
                process_input_fstrs(values[event], state, window)

            case keys.outfile_base:
                update_outfile_str(state, window)

            case event if event in (keys.postfix, keys.prefix, keys.nofix):
                state.fix = event
                update_outfile_str(state, window)

            case keys.subfolder:
                state.subfolder = values[event]
                process_inputs(state, window)

            case keys.n_files:
                process_n_files(values[keys.n_files], window[event])  # type: ignore

            case keys.verbosity:
                set_logging_level_from_verbosity(values[event])

            case keys.open_webview:
                html_code, repo_name = values[event]
                open_webview(html_code, repo_name, gui=True)

    return recreate_window


def execute(  # pylint: disable=too-many-branches
    window: sg.Window,
    values: dict,
    state: GUIState,
) -> None:

    start_time = time.time()
    logger.info(f"{values = }")

    buttons = WindowButtons(window)

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

    if values[keys.blame_history] == DYNAMIC:
        popup("Error", "Dynamic blame history not supported in GUI")
        return

    args = Args()
    settings_schema: dict[str, Any] = SettingsFile.SETTINGS_SCHEMA["properties"]
    for key, value in settings_schema.items():
        if key not in {
            keys.profile,
            keys.fix,
            keys.n_files,
            keys.format,
            keys.since,
            keys.until,
            keys.multi_core,
            keys.gui_settings_full_path,
        }:
            if value["type"] == "array":
                setattr(args, key, shlex.split(values[key]))  # type: ignore
            else:
                setattr(args, key, values[key])

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
    args.format = formats

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

    logger.info(f"{args = }")
    buttons.disable_all()
    window.perform_long_operation(
        lambda: gitinspector_main(args, start_time, window), keys.end
    )


if __name__ == "__main__":
    current_settings: Settings
    error: str
    current_settings, error = SettingsFile.load()
    multiprocessing.freeze_support()
    run(current_settings)
