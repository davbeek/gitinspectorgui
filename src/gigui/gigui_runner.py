import multiprocessing
import os
import select
import sys
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor
from cProfile import Profile
from logging import getLogger

# import multiprocessing.util as util
from multiprocessing.managers import SyncManager
from pathlib import Path
from queue import Queue

import gigui.repo_runner as repo_runner
from gigui import _logging
from gigui._logging import set_logging_level_from_verbosity, start_logging_listener
from gigui.args_settings import Args, MiniRepo
from gigui.constants import (
    DEFAULT_FILE_BASE,
    DEFAULT_VERBOSITY,
    DYNAMIC,
    FIRST_PORT,
    MAX_BROWSER_TABS,
    STATIC,
)
from gigui.gui.psg_support import is_git_repo
from gigui.keys import Keys
from gigui.repo_runner import RepoRunner
from gigui.typedefs import FileStr
from gigui.utils import (
    get_dir_matches,
    log,
    log_analysis_end_time,
    non_hex_chars_in_list,
    out_profile,
    to_posix_fstr,
    to_posix_fstrs,
)

# pylint: disable=too-many-arguments disable=too-many-positional-arguments

logger = getLogger(__name__)


# util.log_to_stderr(logging.DEBUG)
# util.log_to_stderr(logging.WARNING)


class GIGUIRunner:
    args: Args

    def __init__(self, args: Args) -> None:
        self.args = args

        self.manager: SyncManager | None = None
        self.server_started_events: list[threading.Event] = []
        self.server_done_events: list[threading.Event] = []
        self.stop_all_event: threading.Event
        self.host_port_queue: Queue

    def run_repos(self, start_time: float) -> None:
        profiler: Profile | None = None
        repo_lists: list[list[MiniRepo]] = []
        len_repos: int = 0
        dir_strs: list[FileStr]
        dirs_sorted: list[FileStr]

        self._set_options()

        dir_strs = get_dir_matches(self.args.input_fstrs)
        dirs_sorted = sorted(dir_strs)
        for dir_str in dirs_sorted:
            repo_lists.extend(self.get_repos(Path(dir_str), self.args.depth))
        len_repos = self.total_len(repo_lists)

        if len_repos == 0:
            logger.warning("No repositories found, exiting.")
            return

        if not self._check_options(len_repos):
            return

        if len_repos == 1:
            # Set multicore to false, because multicore is not useful for a single repo.
            self.args.multicore = False
            self.stop_all_event = threading.Event()
            self.host_port_queue = Queue()
        else:
            self.manager = multiprocessing.Manager()
            self.stop_all_event = self.manager.Event()
            self.host_port_queue = self.manager.Queue()
        self.host_port_queue.put(FIRST_PORT)

        if self.args.multicore:
            self.process_repos_multicore(
                repo_lists,
                len_repos,
                start_time,
            )
        else:  # single core
            self.process_repos_singlecore(
                repo_lists,
                len_repos,
                start_time,
            )

        # Cleanup resources
        self.host_port_queue.get()  # Need to remove the last port value to avoid a deadlock
        if self.manager:
            self.manager.shutdown()
        out_profile(profiler, self.args.profile)
        log("Done")

    def _check_options(self, len_repos: int) -> bool:
        if (
            self.args.blame_history == STATIC
            and self.args.formats
            and self.args.formats != ["html"]
        ):
            logger.warning(
                "Static blame history is supported only for html or no output formats.\n"
            )
            return False
        if self.args.blame_history == DYNAMIC and self.args.formats != []:
            logger.warning(
                "Dynamic blame history is available only when no output formats are "
                "selected, because it is generated on the fly and the output cannot be "
                "stored in a file."
            )
            return False
        if not len_repos:
            log(
                "Missing search path. Specify a valid relative or absolute search "
                "path. E.g. '.' for the current directory."
            )
            return False
        if len_repos > 1 and self.args.fix == Keys.nofix:
            log(
                "Multiple repos detected and nofix option selected.\n"
                "Multiple repos need the (default prefix) or postfix option."
            )
            return False
        if (
            not self.args.formats
            and self.args.view
            and len_repos > 1
            and self.args.dry_run == 0
        ):
            if len_repos > MAX_BROWSER_TABS:
                logger.warning(
                    f"No output formats selected and number of {len_repos} repositories "
                    f"exceeds the maximum number of {MAX_BROWSER_TABS} browser tabs.\n"
                    "Select an output format or set dry run."
                )
                return False
        if len_repos > 1 and self.args.fix == Keys.nofix and self.args.formats:
            log(
                "Multiple repos detected and nofix option selected for file output.\n"
                "Multiple repos with file output need the (default prefix) or postfix option."
            )
            return False
        if not self.args.view and not self.args.formats and self.args.dry_run == 0:
            log(
                "View option not set and no output formats selected.\n"
                "Set the view option and/or an output format."
            )
            return False

        if non_hex := non_hex_chars_in_list(self.args.ex_revisions):
            log(
                f"Non-hex characters {" ". join(non_hex)} not allowed in exclude "
                f"revisions option {", ". join(self.args.ex_revisions)}."
            )
            return False
        return True

    def _set_options(self) -> None:
        if self.args.profile:
            profiler = Profile()
            profiler.enable()
        if self.args.dry_run == 1:
            self.args.copy_move = 0
        self.args.include_files = (
            self.args.include_files if self.args.include_files else ["*"]
        )
        self.args.outfile_base = (
            self.args.outfile_base if self.args.outfile_base else DEFAULT_FILE_BASE
        )

        self.args.input_fstrs = to_posix_fstrs(self.args.input_fstrs)
        self.args.outfile_base = to_posix_fstr(self.args.outfile_base)
        self.args.subfolder = to_posix_fstr(self.args.subfolder)
        self.args.include_files = to_posix_fstrs(self.args.include_files)
        self.args.ex_files = to_posix_fstrs(self.args.ex_files)

        if self.args.verbosity is None:
            self.args.verbosity = DEFAULT_VERBOSITY
        set_logging_level_from_verbosity(self.args.verbosity)
        logger.debug(f"{self.args = }")  # type: ignore

    def get_repos(self, dir_path: Path, depth: int) -> list[list[MiniRepo]]:
        """
        Recursively retrieves a list of repositories from a given directory path up to a
        specified depth.

        Args:
            - dir_path (Path): The directory path to search for repositories.
            - depth (int): The depth of recursion to search for repositories. A depth of 0
            means only the given directory is checked.

        Returns:
            list[list[RepoGI]]: A list of lists, where each inner list contains repositories
            found in the same directory.

        Notes:
            - If the given path is not a directory, an empty list is returned.
            - If the given path is a Git repository, a list containing a single list with
            one RepoGI object is returned.
            - If the depth is greater than 0, the function will recursively search
            subdirectories for Git repositories.
        """
        repo_lists: list[list[MiniRepo]]
        if self.is_dir_safe(dir_path):
            if is_git_repo(dir_path):
                return [
                    [MiniRepo(dir_path.name, dir_path, self.args)]
                ]  # independent of depth
            elif depth == 0:
                # For depth == 0, the input itself must be a repo, which is not the case.
                return []
            else:  # depth >= 1:
                subdirs: list[Path] = self.subdirs_safe(dir_path)
                repos: list[MiniRepo] = [
                    MiniRepo(subdir.name, subdir, self.args)
                    for subdir in subdirs
                    if is_git_repo(subdir)
                ]
                repos = sorted(repos, key=lambda x: x.name)
                other_dirs: list[Path] = [
                    subdir for subdir in subdirs if not is_git_repo(subdir)
                ]
                other_dirs = sorted(other_dirs)
                repo_lists = [repos] if repos else []
                for other_dir in other_dirs:
                    repo_lists.extend(self.get_repos(other_dir, depth - 1))
                return repo_lists
        else:
            log(f"Path {dir_path} is not a directory")
            return []

    def is_dir_safe(self, path: Path) -> bool:
        try:
            return os.path.isdir(path)
        except PermissionError:
            logger.warning(f"Permission denied for path {str(path)}")
            return False

    def subdirs_safe(self, path: Path) -> list[Path]:
        try:
            if not self.is_dir_safe(path):
                return []
            subs: list[FileStr] = os.listdir(path)
            sub_paths = [path / sub for sub in subs]
            return [path for path in sub_paths if self.is_dir_safe(path)]
        # Exception when the os does not allow to list the contents of the path dir:
        except PermissionError:
            logger.warning(f"Permission denied for path {str(path)}")
            return []

    # Process multiple repositories in case len(repos) > 1 on multiple cores.
    def process_repos_multicore(
        self,
        repo_lists: list[list[MiniRepo]],
        len_repos: int,
        start_time: float,
    ) -> None:
        logging_queue: Queue = self.manager.Queue()  # type: ignore
        listener = start_logging_listener(logging_queue, self.args.verbosity)
        max_workers = (
            multiprocessing.cpu_count()
            if not self.args.blame_history == DYNAMIC
            else min(len_repos, MAX_BROWSER_TABS)
        )
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_logging.ini_for_multiprocessing_cli,
            initargs=(logging_queue, self.args.verbosity),
        ) as process_executor:
            future_to_mini_repo: dict[Future, MiniRepo] = {}
            for repos in repo_lists:
                len_repos = len(repos)
                repo_parent_str = str(repos[0].location.resolve().parent)
                log("Output in folder " + repo_parent_str)
                for mini_repo in repos:
                    server_started_event = self.manager.Event()  # type: ignore
                    self.server_started_events.append(server_started_event)
                    server_done_event = self.manager.Event()  # type: ignore
                    self.server_done_events.append(server_done_event)
                    future_to_mini_repo |= {
                        process_executor.submit(
                            repo_runner.process_repo_multicore,
                            mini_repo,
                            server_started_event,
                            server_done_event,
                            self.stop_all_event,
                            self.host_port_queue,
                        ): mini_repo
                    }
            try:
                servers_started: bool = False
                nr_started: int = 0
                nr_started_prev: int = -1
                nr_done: int = 0
                nr_done_prev: int = -1
                while not servers_started:
                    nr_started = sum(
                        event.is_set() for event in self.server_started_events
                    )
                    if nr_started != nr_started_prev:
                        nr_started_prev = nr_started
                        logger.debug(
                            f"Main: {nr_started} of {len(self.server_started_events)} "
                            "server started events are set"
                        )
                    if nr_started == len(self.server_started_events):
                        # Flush the reading buffer by reading and discarding any existing input
                        while select.select([sys.stdin], [], [], 0.1)[0]:
                            sys.stdin.read(1)
                        log_analysis_end_time(start_time)
                        if self.args.blame_history == DYNAMIC:
                            log("Close all browser tabs or press Enter to quit.")
                        servers_started = True
                    time.sleep(0.05)
                while True:
                    nr_done = sum(event.is_set() for event in self.server_done_events)
                    if nr_done != nr_done_prev:
                        nr_done_prev = nr_done
                        logger.debug(
                            f"Main: {nr_done} of {len(self.server_done_events)} "
                            "server done events set"
                        )
                    if nr_done == len(self.server_done_events):
                        break
                    if (
                        not self.stop_all_event.is_set()
                        and select.select([sys.stdin], [], [], 0.1)[0]
                    ):
                        if input() == "":
                            logger.debug("Main: set stop event")
                            self.stop_all_event.set()  # type: ignore
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logger.debug("Main: keyboard interrupt received")
            finally:
                listener.stop()

    def process_repos_singlecore(
        self,
        repo_lists: list[list[MiniRepo]],
        len_repos: int,
        start_time: float,
    ) -> None:
        """Processes repositories on a single core.

        Outputs repositories in batches, where each batch contains repositories
        from a single folder.

        Args:
            args: Command-line arguments.
            repo_lists: List of lists of repositories to process.
            len_repos: Total number of repositories.
            outfile_base: Base name for output files.
            gui_window: GUI window instance, if any.
            start_time: Start time of the process.
            shared_data: Shared data dictionary for inter-process communication.
        """

        count = 1
        runs = 0
        while repo_lists:
            # output a batch of repos from the same folder in a single run
            repos = repo_lists.pop(0)
            prefix: str = "Output in folder" if self.args.formats else "Folder"
            log(prefix + str(repos[0].location.resolve().parent))
            for mini_repo in repos:
                log(" " * 4 + f"{mini_repo.name} repository ({count} of {len_repos})")
                server_started_event = threading.Event()  # type: ignore
                server_done_event = threading.Event()  # type: ignore
                self.server_done_events.append(server_done_event)
                repo_runner = RepoRunner(
                    mini_repo,
                    server_started_event,
                    server_done_event,
                    self.stop_all_event,
                    self.host_port_queue,
                )
                repo_runner.run_repo(
                    len_repos,
                    start_time,
                )
                count += 1
            runs += 1
        log_analysis_end_time(start_time)
        if not self.args.formats and self.args.view:
            try:
                # Flush the reading buffer by reading and discarding any existing input
                while select.select([sys.stdin], [], [], 0.1)[0]:
                    sys.stdin.read(1)
                    log("Close all browser tabs or press Enter to quit.")
                nr_done: int = 0
                nr_done_prev: int = -1
                while True:
                    nr_done = sum(event.is_set() for event in self.server_done_events)
                    if nr_done != nr_done_prev:
                        nr_done_prev = nr_done
                        logger.info(
                            f"Main: {nr_done} of {len(self.server_done_events)} "
                            "server done events set"
                        )
                    if nr_done == len(self.server_done_events):
                        break
                    if (
                        not self.stop_all_event.is_set()
                        and select.select([sys.stdin], [], [], 0.1)[0]
                    ):
                        if input() == "":
                            logger.info("Main: set stop event")
                            self.stop_all_event.set()  # type: ignore
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logger.info("Main: keyboard interrupt received")

    def await_server_done_events(self) -> None:
        try:
            print("Awaiting server started events")
            show_stop_message = self.args.blame_history == DYNAMIC
            nr_done: int = 0
            nr_done_prev: int = -1
            while True:
                nr_done = sum(event.is_set() for event in self.server_done_events)
                if nr_done == len(self.server_done_events):
                    break
                if show_stop_message:
                    log("Close all browser tabs or press Enter to quit.")
                    show_stop_message = False
                if nr_done != nr_done_prev:
                    nr_done_prev = nr_done
                    logger.info(
                        f"{nr_done} of {len(self.server_done_events)} done events set",
                    )
                if (
                    not self.stop_all_event.is_set()
                    and select.select([sys.stdin], [], [], 0.1)[0]
                ):
                    if input().lower() == "q":
                        self.stop_all_event.set()  # type: ignore
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("GI: keyboard interrupt received")

    @staticmethod
    def total_len(repo_lists: list[list[MiniRepo]]) -> int:
        return sum(len(repo_list) for repo_list in repo_lists)


# Main function to run the analysis and create the output
def run_repos(args: Args, start_time: float) -> None:
    GIGUIRunner(args).run_repos(start_time)
