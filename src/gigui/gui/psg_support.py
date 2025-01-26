import shlex
import webbrowser
from copy import copy
from dataclasses import asdict
from pathlib import Path

import PySimpleGUI as sg  # type: ignore
from git import InvalidGitRepositoryError, NoSuchPathError
from git import Repo as GitRepo

from gigui.args_settings import Settings, SettingsFile
from gigui.constants import (
    AVAILABLE_FORMATS,
    DEFAULT_FILE_BASE,
    DISABLED_COLOR,
    ENABLED_COLOR,
    INVALID_INPUT_COLOR,
    PARENT_HINT,
    REPO_HINT,
    VALID_INPUT_COLOR,
)
from gigui.keys import Keys
from gigui.tiphelp import Help
from gigui.typedefs import FilePattern, FileStr
from gigui.utils import get_posix_dir_matches_for, to_posix_fstrs

keys = Keys()


class PSGBase:
    def __init__(self, settings: Settings):
        self.settings: Settings = settings
        self.window: sg.Window

        # All file strings are in POSIX format, containing only forward slashes as path
        # separators, apart from outfile_base which is not supposed to contain path
        # separators.
        self.col_percent: int = self.settings.col_percent
        self.gui_settings_full_path: bool = self.settings.gui_settings_full_path
        self.multithread: bool = self.settings.multithread
        self.input_fstrs: list[FilePattern] = []  # as entered by user
        self.input_fstr_matches: list[FileStr] = []
        self.input_repo_path: Path | None = None
        self.fix: str = keys.prefix
        self.outfile_base: FileStr = DEFAULT_FILE_BASE
        self.subfolder: FileStr = ""
        self.subfolder_valid: bool = True
        self.buttons: list[str] = []

        self.buttons: list[str] = [
            keys.run,
            keys.clear,
            keys.save,
            keys.save_as,
            keys.load,
            keys.reset,
            keys.help,
            keys.about,
            keys.browse_input_fstr,
        ]

    def window_state_from_settings(self) -> None:
        settings = copy(
            self.settings
        ).as_system()  # ensure all file strings are in system format
        settings_dict = asdict(settings)
        # settings_min is settings dict with 6 keys removed: keys.fix - keys.multithread
        settings_min = {
            key: value
            for key, value in settings_dict.items()
            if key
            not in {
                keys.fix,
                keys.formats,
                keys.gui_settings_full_path,
                keys.profile,
                keys.multithread,
            }
        }
        for key, val in settings_min.items():
            if isinstance(val, list):
                value_list = " ".join(val)
                self.window.Element(key).Update(value=value_list)  # type: ignore
            else:
                self.window.Element(key).Update(value=val)  # type: ignore

        # default values of boolean window.Element are False
        self.window.Element(settings.fix).Update(value=True)  # type: ignore

        if settings.formats:
            for key in set(AVAILABLE_FORMATS):
                self.window.Element(key).Update(  # type:ignore
                    value=key in settings.formats
                )

        self.window.write_event_value(keys.input_fstrs, " ".join(settings.input_fstrs))
        self.window.write_event_value(keys.outfile_base, settings.outfile_base)
        self.window.write_event_value(
            keys.include_files, " ".join(settings.include_files)
        )
        self.window.write_event_value(keys.subfolder, settings.subfolder)
        self.window.write_event_value(keys.verbosity, settings.verbosity)

        # First set column height too big, then set it to the correct value to ensure
        # correct displaying of the column height
        self.window.write_event_value(
            keys.col_percent, min(settings.col_percent + 5, 100)
        )
        self.window.write_event_value(keys.col_percent, settings.col_percent)
        self.window.write_event_value(keys.blame_history, settings.blame_history)
        if settings.gui_settings_full_path:
            settings_fstr = str(SettingsFile.get_location_path())
        else:
            settings_fstr = SettingsFile.get_location_path().stem
        self.window[keys.settings_file].update(value=settings_fstr)  # type: ignore

    def update_outfile_str(self) -> None:
        def get_outfile_str() -> str:

            def get_rename_file() -> str:
                if self.input_repo_path:
                    repo_name = self.input_repo_path.stem
                else:
                    repo_name = REPO_HINT

                if self.fix == keys.postfix:
                    return f"{self.outfile_base}-{repo_name}"
                elif self.fix == keys.prefix:
                    return f"{repo_name}-{self.outfile_base}"
                else:  # fix == keys.nofix
                    return self.outfile_base

            if not self.input_fstrs or not self.input_fstr_matches:
                return ""

            out_name = get_rename_file()
            if self.input_repo_path:
                return str(self.input_repo_path.parent) + "/" + out_name
            else:
                return PARENT_HINT + out_name

        self.window[keys.outfile_path].update(value=get_outfile_str())  # type: ignore

    def update_settings_file_str(
        self,
        full_path: bool,
    ) -> None:
        if full_path:
            file_string = str(SettingsFile.get_location_path())
        else:
            file_string = SettingsFile.get_location_path().stem
        self.window[keys.settings_file].update(value=file_string)  # type: ignore

    def process_input_fstrs(self, input_fstr_patterns: str) -> None:
        try:
            input_fstrs: list[FileStr] = shlex.split(input_fstr_patterns)  # type: ignore
        except ValueError:
            self.window[keys.input_fstrs].update(background_color=INVALID_INPUT_COLOR)  # type: ignore
            return
        self.input_fstrs = to_posix_fstrs(input_fstrs)
        self.process_inputs()

    def process_inputs(self) -> None:
        if not self.input_fstrs:
            self.input_fstr_matches = []
            self.input_repo_path = None
            enable_element(self.window[keys.prefix])  # type: ignore
            enable_element(self.window[keys.postfix])  # type: ignore
            enable_element(self.window[keys.nofix])  # type: ignore
            enable_element(self.window[keys.depth])  # type: ignore
            self.update_outfile_str()
            return

        matches: list[FileStr] = self.get_posix_dir_matches(self.input_fstrs, self.window[keys.input_fstrs])  # type: ignore
        self.input_fstr_matches = matches

        if len(matches) == 1 and is_git_repo(Path(matches[0])):
            self.input_repo_path = Path(matches[0])
            enable_element(self.window[keys.prefix])  # type: ignore
            enable_element(self.window[keys.postfix])  # type: ignore
            enable_element(self.window[keys.nofix])  # type: ignore
            disable_element(self.window[keys.depth])  # type: ignore
            self.update_outfile_str()
            self.check_subfolder()
        else:
            self.input_repo_path = None
            enable_element(self.window[keys.prefix])  # type: ignore
            enable_element(self.window[keys.postfix])  # type: ignore
            disable_element(self.window[keys.nofix])  # type: ignore
            enable_element(self.window[keys.depth])  # type: ignore
            self.update_outfile_str()

    def get_posix_dir_matches(
        self, patterns: list[FilePattern], sg_input: sg.Input, colored: bool = True
    ) -> list[FileStr]:
        all_matches: list[FileStr] = []
        for pattern in patterns:
            matches: list[FileStr] = get_posix_dir_matches_for(pattern)
            if not matches:
                if colored:
                    sg_input.update(background_color=INVALID_INPUT_COLOR)
                return []
            else:
                all_matches.extend(matches)
        sg_input.update(background_color=VALID_INPUT_COLOR)
        unique_matches = []
        for match in all_matches:
            if match not in unique_matches:
                unique_matches.append(match)
        return unique_matches

    def check_subfolder(self) -> None:
        # check_subfolder() is called by process_inputs() when state.input_repo_path
        # is valid
        if not self.subfolder:
            self.subfolder_valid = True
            self.window[keys.subfolder].update(background_color=VALID_INPUT_COLOR)  # type: ignore
            return

        subfolder_exists: bool
        repo = GitRepo(self.input_repo_path)  # type: ignore
        tree = repo.head.commit.tree

        subfolder_path = self.subfolder.split("/")
        if not subfolder_path[0]:
            subfolder_path = subfolder_path[1:]
        if not subfolder_path[-1]:
            subfolder_path = subfolder_path[:-1]
        subfolder_exists = True
        for part in subfolder_path:
            try:
                # Note that "if part in tree" does not work properly:
                # - It works for the first part, but not for the second part.
                # - For the second part, it always returns False, even if the
                #   part (subfolder) exists.
                tree_or_blob = tree[part]  # type: ignore
                if not tree_or_blob.type == "tree":  # Check if the part is a directory
                    subfolder_exists = False
                    break
                tree = tree_or_blob
            except KeyError:
                subfolder_exists = False
                break

        if subfolder_exists:
            self.subfolder_valid = True
            self.window[keys.subfolder].update(background_color=VALID_INPUT_COLOR)  # type: ignore
        else:
            self.subfolder_valid = False
            self.window[keys.subfolder].update(background_color=INVALID_INPUT_COLOR)  # type: ignore

    def process_n_files(self, n_files_str: str, input_field: sg.Input) -> None:
        # Filter out any initial zero and all non-digit characters
        filtered_str = "".join(filter(str.isdigit, n_files_str)).lstrip("0")
        input_field.update(filtered_str)

    def disable_buttons(self) -> None:
        for button in self.buttons:
            self.update_button_state(button, disabled=True)
            self.update_button_state(keys.stop, disabled=True)

    def configure_buttons_for_idle(self) -> None:
        for button in self.buttons:
            self.update_button_state(button, disabled=False)
        self.update_button_state(keys.stop, disabled=True)

    def enable_stop_button(self) -> None:
        self.update_button_state(keys.stop, disabled=False)

    def update_button_state(self, button: str, disabled: bool) -> None:
        if disabled:
            color = DISABLED_COLOR
        else:
            color = ENABLED_COLOR
        self.window[button].update(disabled=disabled, button_color=color)  # type: ignore


def disable_element(ele: sg.Element) -> None:
    ele.update(disabled=True)


def enable_element(ele: sg.Element) -> None:
    ele.update(disabled=False)


def help_window() -> None:
    def help_text(string) -> sg.Text:
        return sg.Text(string, text_color="black", background_color="white", pad=(0, 0))

    def hyperlink_text(url) -> sg.Text:
        return sg.Text(
            url,
            enable_events=True,
            font=("Helvetica", 12, "underline"),
            text_color="black",
            key="URL " + url,
            background_color="white",
            pad=(0, 0),
        )

    txt_start, url, txt_end = Help.help_doc
    layout = [
        [
            help_text(txt_start),
            hyperlink_text(url),
            help_text(txt_end),
        ],
        [sg.VPush()],  # Add vertical space
        [sg.VPush()],  # Add vertical space
        [sg.Column([[sg.Button("OK", key="OK_BUTTON")]], justification="center")],
    ]

    window = sg.Window(
        "Help Documentation",
        layout,
        finalize=True,
        keep_on_top=True,
        background_color="white",
    )

    while True:
        event, _ = window.read()  # type: ignore
        if event == sg.WINDOW_CLOSED or event == "OK_BUTTON":
            break
        if event.startswith("URL "):
            url = event.split()[1]
            webbrowser.open(url)

    window.close()


def popup(title, message):
    sg.popup(
        title,
        message,
        keep_on_top=True,
        text_color="black",
        background_color="white",
    )


def popup_custom(title, message, user_input=None) -> str | None:
    layout = [[sg.Text(message, text_color="black", background_color="white")]]
    if user_input:
        layout += [
            [sg.Text(user_input, text_color="black", background_color="white")],
            [sg.OK()],
        ]
    else:
        layout += [[sg.OK(), sg.Cancel()]]
    window = sg.Window(title, layout, keep_on_top=True)
    event, _ = window.read()  # type: ignore
    window.close()
    return None if event != "OK" else event


def log(*args: str, color=None) -> None:
    sg.cprint("\n".join(args), c=color)


def use_single_repo(input_paths: list[Path]) -> bool:
    return len(input_paths) == 1 and is_git_repo(input_paths[0])


def is_git_repo(path: Path) -> bool:
    try:
        git_path = path / ".git"
        if git_path.is_symlink():
            git_path = git_path.resolve()
            if not git_path.is_dir():
                return False
        elif not git_path.is_dir():
            return False
    except (PermissionError, TimeoutError):  # git_path.is_symlink() may time out
        return False

    try:
        # The default True value of expand_vars leads to confusing warnings from
        # GitPython for many paths from system folders.
        repo = GitRepo(path, expand_vars=False)
        return not repo.bare
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False
