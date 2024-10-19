# noinspection PyPep8Naming
import logging
import multiprocessing
import sys
import time
from datetime import datetime
from multiprocessing import Process
from pathlib import Path
from typing import Any

import PySimpleGUI as sg  # type: ignore[import-untyped]

from gigui import _logging, utils
from gigui._logging import set_logging_level_from_verbosity
from gigui.args_settings import Args, Settings, SettingsFile
from gigui.constants import (
    AVAILABLE_FORMATS,
    DEBUG_SHOW_MAIN_EVENT_LOOP,
    DEFAULT_EXTENSIONS,
)
from gigui.gitinspector import main as gitinspector_main
from gigui.gui.psg_support import (
    GUIState,
    WindowButtons,
    disable_element,
    enable_element,
    help_window,
    log,
    popup,
    popup_custom,
    process_input_patterns,
    update_col_percent,
    update_column_height,
    update_outfile_str,
    update_settings_file_str,
    window_state_from_settings,
)
from gigui.gui.psg_window import make_window
from gigui.keys import Keys
from gigui.tiphelp import Help, Tip
from gigui.utils import open_webview, str_split_comma

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
    state: GUIState = GUIState(settings.col_percent)
    utils.gui = True

    # Is set to True when handling "Reset settings file" menu item
    recreate_window: bool = False

    if sys.platform == "darwin":
        sg.set_options(font=("Any", 12))

    window: sg.Window
    window = make_window()
    utils.gui_window = window
    _logging.gui_window = window

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
            not event
            == keys.debug
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
                state = process_input_patterns(state, window[keys.input_fstrs], window)  # type: ignore
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
                    SettingsFile.show()
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
                state.input_patterns = str_split_comma(values[event])
                state = process_input_patterns(state, window[event], window)  # type: ignore

            case keys.outfile_base:
                state.outfile_base = values[keys.outfile_base]
                update_outfile_str(state, window)

            case event if event in (keys.postfix, keys.prefix, keys.nofix):
                state.fix = event
                update_outfile_str(state, window)

            case keys.auto:
                if values[keys.auto] is True:
                    window.Element(keys.html).Update(value=False)  # type: ignore
                    window.Element(keys.excel).Update(value=False)  # type: ignore
                else:
                    window.Element(keys.html).Update(value=True)  # type: ignore

            case keys.html | keys.excel:
                if values[event] is True:
                    window.Element(keys.auto).Update(value=False)  # type: ignore
                else:
                    if all(values[key] == 0 for key in AVAILABLE_FORMATS):
                        window.Element(keys.auto).Update(value=True)  # type: ignore

            case keys.include_files:
                if values[keys.include_files]:
                    disable_element(window[keys.n_files])  # type: ignore
                else:
                    enable_element(window[keys.n_files])  # type: ignore

            case keys.verbosity:
                set_logging_level_from_verbosity(values[event])

            case keys.open_webview:
                html_code, repo_name = values[event]
                webview_process = Process(
                    target=open_webview, args=(html_code, repo_name)
                )
                webview_process.daemon = True
                webview_process.start()
    return recreate_window


def execute(  # pylint: disable=too-many-branches
    window: sg.Window,
    values: dict,
    state: GUIState,
) -> None:

    start_time = time.time()
    logger.info(f"{values = }")

    buttons = WindowButtons(window)

    if state.input_patterns and not state.input_fstrs:
        popup("Error", "Input folder path not valid")
        return

    if not state.input_patterns:
        popup("Error", "Input folder path empty")
        return

    if not state.outfile_base:
        popup("Error", "Output file base empty")
        return

    args = Args()
    settings_schema: dict[str, Any] = SettingsFile.SETTINGS_SCHEMA["properties"]
    for key, value in settings_schema.items():
        if key not in {
            keys.profile,
            keys.fix,
            keys.format,
            keys.extensions,
            keys.since,
            keys.until,
            keys.multi_thread,
            keys.multi_core,
            keys.gui_settings_full_path,
        }:
            if value["type"] == "array":
                setattr(args, key, str_split_comma(values[key]))  # type: ignore
            else:
                setattr(args, key, values[key])

    if values[keys.prefix]:
        args.fix = keys.prefix
    elif values[keys.postfix]:
        args.fix = keys.postfix
    else:
        args.fix = keys.nofix

    out_format_selected = []
    for key in AVAILABLE_FORMATS:
        if values[key]:
            out_format_selected.append(key)
    args.format = out_format_selected

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

    args.extensions = (
        str_split_comma(values[keys.extensions])
        if values[keys.extensions]
        else DEFAULT_EXTENSIONS
    )

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
