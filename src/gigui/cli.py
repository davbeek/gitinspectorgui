import multiprocessing
import os
import sys
import time
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from logging import getLogger
from pathlib import Path

from gigui import _logging, gigui_runner
from gigui._logging import log, set_logging_level_from_verbosity
from gigui.args_settings import Args, CLIArgs, Settings, SettingsFile
from gigui.cli_arguments import define_arguments
from gigui.constants import AVAILABLE_FORMATS, DEFAULT_EXTENSIONS
from gigui.gui import psg
from gigui.tiphelp import Help
from gigui.typedefs import FileStr
from gigui.utils import get_dir_matches

# Limit the width of the help text to 80 characters.
os.environ["COLUMNS"] = "90"

logger = getLogger(__name__)


def main() -> None:
    settings: Settings = Settings()
    start_time = time.time()

    parser = ArgumentParser(
        prog="gitinspectorgui",
        description="".join(Help.help_doc),
        formatter_class=RawDescriptionHelpFormatter,
    )
    define_arguments(parser)

    # For zero arguments, print help and exit.
    if len(sys.argv) == 1:
        parser.print_help()
        return

    namespace = parser.parse_args()

    _logging.ini_for_cli(namespace.verbosity)

    if namespace.input_fstrs:
        input_fstrs = [
            Path(fstr).resolve().as_posix() for fstr in namespace.input_fstrs
        ]
        matches: list[FileStr] = get_dir_matches(input_fstrs)
        if not matches:
            return
        else:
            namespace.input_fstrs = input_fstrs

    if namespace.reset_file:
        settings = SettingsFile.reset()
        log(f"Settings file reset to {SettingsFile.get_location_path()}.")

    if namespace.reset:
        settings = Settings()
        log("Settings reset to default values.")

    if namespace.load is not None:
        path_str = namespace.load
        if not path_str:
            logger.error(
                "--load PATH: PATH missing. Specify a path for the settings file."
            )
            return
        settings, error = SettingsFile.load_from(path_str)
        if error:
            logger.error(
                f"--load {path_str}: Error loading settings from {path_str}: {error}"
            )
            return
        SettingsFile.set_location(path_str)
        # The loaded settings are ignored, because the program exits immediately after
        # executing this command.
        log(f"Settings loaded from {path_str}.")

    if not namespace.reset_file and not namespace.reset and namespace.load is None:
        settings = load_settings(namespace.save, namespace.save_as)

    gui_settings_full_path = settings.gui_settings_full_path

    cli_args: CLIArgs = settings.to_cli_args()

    if namespace.run and namespace.input_fstrs:
        log(
            "ERROR: Can only use --run and --input PATH ... together when --run has no "
            "arguments."
        )
        return
    cli_args.update_with_namespace(namespace)

    if cli_args.profile:
        cli_args.view = False

    # Validate formats
    for fmt in cli_args.formats:
        if fmt not in AVAILABLE_FORMATS:
            # Print error message and exit
            parser.error(
                f"Invalid format: {fmt}. Available formats: {', '.join(AVAILABLE_FORMATS)}"
            )

    if not cli_args.extensions:
        cli_args.extensions = DEFAULT_EXTENSIONS

    logger.debug(f"{cli_args = }")  # type: ignore

    args: Args = cli_args.create_args()
    args.input_fstrs = [Path(p).resolve().as_posix() for p in args.input_fstrs]

    if namespace.save:
        settings = cli_args.create_settings()
        settings.save()
        log(f"Settings saved to {SettingsFile.get_location_path()}.")

    if namespace.save_as is not None:
        path_str = namespace.save_as
        if not path_str:
            logger.error(
                "--save-as PATH: PATH is missing. "
                "Specify a path for the settings file."
            )
            return
        settings = cli_args.create_settings()

        if Path(path_str).suffix == ".json":
            path = Path(path_str).resolve()
            settings.save_as(path)
            log(f"Settings saved to {path}.")
        else:
            logger.error(f"--save-as {path_str}: {path_str} should be a JSON file.")

    if namespace.show is True:
        SettingsFile.show()
        log("")

    if namespace.gui:
        psg.run_gui(Settings.from_args(args, gui_settings_full_path))
    elif namespace.run:
        gigui_runner.run_repos(args, start_time)
    elif not namespace.save and not namespace.save_as and not namespace.show:
        log(
            "This command has no effect. Use --run/-r or --gui/-g to run the program, or "
            "use --save or --save-as to save settings or --show to display settings."
        )
        return


def load_settings(save: bool, save_as: str) -> Settings:
    settings: Settings
    error: str
    settings, error = SettingsFile.load()
    set_logging_level_from_verbosity(settings.verbosity)
    if error:
        logger.warning("Cannot load settings file, loading default settings.")
        if not save and not save_as:
            log("Save settings (--save) to avoid this message.")
    return settings


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)
