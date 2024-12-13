import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from pygit2.enums import SortMode
from pygit2.repository import Repository

from gigui.blame_reader import BlameHistoryReader, BlameReader
from gigui.data import CommitGroup, FileStat, Person, PersonsDB, PersonStat
from gigui.repo_reader import RepoReader
from gigui.typedefs import Author, FileStr, SHAShort
from gigui.utils import divide_to_percentage, log

logger = logging.getLogger(__name__)


class GIRepo:
    blame_history: str

    def __init__(self, name: str, location: Path):
        self.name = name
        self.location = str(location)

        self.path = Path(location).resolve()
        self.pathstr = str(self.path)
        self.persons_db: PersonsDB = PersonsDB()

        self.repo_reader = RepoReader(self.name, self.location, self.persons_db)
        self.blame_reader: BlameReader
        self.blame_history_reader: BlameHistoryReader

        self.stat_tables = StatTables()

        self.author2fstr2fstat: dict[str, dict[str, FileStat]] = {}
        self.fstr2fstat: dict[str, FileStat] = {}
        self.fstr2author2fstat: dict[str, dict[str, FileStat]] = {}
        self.author2pstat: dict[str, PersonStat] = {}

        # Valid only after self.run has been called. This call calculates the sorted
        # versions of self.fstrs and self.star_fstrs.
        self.fstrs: list[str] = []
        self.star_fstrs: list[str] = []

        # Sorted list of non-excluded authors, valid only after self.run has been called.
        self.authors_included: list[Author] = []

        self.fr2f2a2sha_shorts: dict[
            FileStr, dict[FileStr, dict[Author, list[SHAShort]]]
        ] = {}
        self.fr2f2sha_shorts: dict[FileStr, dict[FileStr, list[SHAShort]]] = {}

        # Valid only after self.run has been called with option --blame-history.
        self.fstr2sha_shorts: dict[FileStr, list[SHAShort]] = {}

        self.author2nr: dict[Author, int] = {}  # does not include "*" as author
        self.author_star2nr: dict[Author, int] = {}  # includes "*" as author

        self.sha_short2author: dict[SHAShort, Author] = {}
        self.sha_short2author_nr: dict[SHAShort, int] = {}

    def run(self, thread_executor: ThreadPoolExecutor) -> bool:
        """
        Generate tables encoded as dictionaries in self.stats.

        Returns:
            bool: True after successful execution, False if no stats have been found.
        """

        success: bool
        try:
            success = self._run_no_history(thread_executor)
            if not success:
                return False

            self._set_final_data()
            if self.blame_history != "none":
                self.blame_history_reader = BlameHistoryReader(
                    self.blame_reader.fstr2blames,
                    self.fr2f2sha_shorts,
                    self.repo_reader,
                    self,
                )
            return True
        finally:
            self.repo_reader.git_repo.free()

    def _run_no_history(self, thread_executor: ThreadPoolExecutor) -> bool:
        self.repo_reader.run(thread_executor)

        # Use results from repo_reader to initialize the other classes.
        self.blame_reader = BlameReader(
            self.repo_reader.head_sha_short,
            self.repo_reader,
            self,
        )

        # This calculates all blames but also adds the author and email of
        # each blame to the persons list. This is necessary, because the blame
        # functionality can have another way to set/get the author and email of a
        # commit.
        self.blame_reader.run(thread_executor)

        # Set stats.author2fstr2fstat, the basis of all other stat tables
        self.author2fstr2fstat = self.stat_tables.get_author2fstr2fstat(
            self.repo_reader.fstrs,
            self.repo_reader.fstr2commit_groups,
            self.repo_reader.persons_db,
        )
        if list(self.author2fstr2fstat.keys()) == ["*"]:
            return False

        # Update author2fstr2fstat with line counts for each author.
        self.author2fstr2fstat = self.blame_reader.update_author2fstr2fstat(
            self.author2fstr2fstat
        )

        self.fstr2fstat = self.stat_tables.get_fstr2fstat(
            self.author2fstr2fstat, self.repo_reader.fstr2commit_groups
        )

        # Set self.fstrs and self.star_fstrs and sort by line count
        fstrs = self.fstr2fstat.keys()
        self.star_fstrs = sorted(
            fstrs, key=lambda x: self.fstr2fstat[x].stat.line_count, reverse=True
        )
        if self.star_fstrs and self.star_fstrs[0] == "*":
            self.fstrs = self.star_fstrs[1:]  # remove "*"
        else:
            self.fstrs = self.star_fstrs

        if list(self.fstr2fstat.keys()) == ["*"]:
            return False

        self.fstr2author2fstat = self.stat_tables.get_fstr2author2fstat(
            self.author2fstr2fstat
        )

        self.author2pstat = self.stat_tables.get_author2pstat(
            self.author2fstr2fstat, self.repo_reader.persons_db
        )

        total_insertions = self.author2pstat["*"].stat.insertions
        total_lines = self.author2pstat["*"].stat.line_count

        self.stat_tables.calculate_percentages(
            self.fstr2fstat, total_insertions, total_lines
        )
        self.stat_tables.calculate_percentages(
            self.author2pstat, total_insertions, total_lines
        )
        for _, fstr2fstat in self.author2fstr2fstat.items():
            self.stat_tables.calculate_percentages(
                fstr2fstat, total_insertions, total_lines
            )
        for _, author2fstat in self.fstr2author2fstat.items():
            self.stat_tables.calculate_percentages(
                author2fstat, total_insertions, total_lines
            )
        return True

    def get_person(self, author: Author | None) -> Person:
        return self.repo_reader.get_person(author)

    def _set_final_data(self) -> None:

        # calculate self.sha_long2author
        for commit in self.repo_reader.git_repo.walk(
            self.repo_reader.git_repo.head.target, SortMode.TIME
        ):
            sha_short = str(commit.short_id)
            author = self.get_person(commit.author.name).author
            self.sha_short2author[sha_short] = author

        self.fr2f2a2sha_shorts = self.fr2f2a2sha_set_to_list(
            self.repo_reader.fr2f2a2sha_short_set
        )

        self.fr2f2sha_shorts = self.fr2f2sha_set_to_list(
            self.get_fr2f2sha_set(self.repo_reader.fr2f2a2sha_short_set)
        )

        for fstr in self.fstrs:
            sha_shorts_fr = set()
            for sha_shorts in self.fr2f2sha_shorts[fstr].values():
                sha_shorts_fr.update(sha_shorts)
            sha_shorts_fr_sorted = sorted(
                sha_shorts_fr, key=lambda x: self.sha_short2nr[x], reverse=True
            )
            self.fstr2sha_shorts[fstr] = sha_shorts_fr_sorted

        authors_included: list[Author] = self.repo_reader.persons_db.authors_included
        self.authors_included = sorted(
            authors_included,
            key=lambda x: self.author2pstat[x].stat.line_count,
            reverse=True,
        )

        for i, author in enumerate(self.authors_included):
            self.author_star2nr[author] = i  # "*" author gets nr 0
        for author in self.persons_db.authors_excluded:
            self.author_star2nr[author] = 0

        self.author2nr = {k: v for k, v in self.author_star2nr.items() if k != "*"}

        for sha_short, author in self.sha_short2author.items():
            self.sha_short2author_nr[sha_short] = self.author2nr[author]

    @property
    def real_authors_included(self) -> list[Author]:
        return [author for author in self.authors_included if not author == "*"]

    # from set to list
    def fr2f2a2sha_set_to_list(
        self, source: dict[FileStr, dict[FileStr, dict[Author, set[SHAShort]]]]
    ) -> dict[FileStr, dict[FileStr, dict[Author, list[SHAShort]]]]:
        target: dict[FileStr, dict[FileStr, dict[Author, list[SHAShort]]]] = {}
        for fstr_root, fstr_root_dict in source.items():
            target[fstr_root] = {}
            for fstr, fstr_dict in fstr_root_dict.items():
                target[fstr_root][fstr] = {}
                for author, sha_shorts in fstr_dict.items():
                    person_author = self.get_person(author).author
                    sha_shorts_sorted = sorted(
                        sha_shorts, key=lambda x: self.sha_short2nr[x], reverse=True
                    )
                    target[fstr_root][fstr][person_author] = sha_shorts_sorted
        return target

    def get_fr2f2sha_set(
        self, source: dict[FileStr, dict[FileStr, dict[Author, set[SHAShort]]]]
    ) -> dict[FileStr, dict[FileStr, set[SHAShort]]]:
        target: dict[FileStr, dict[FileStr, set[SHAShort]]] = {}
        for fstr_root, fstr_root_dict in source.items():
            target[fstr_root] = {}
            for fstr, fstr_dict in fstr_root_dict.items():
                target[fstr_root][fstr] = set()
                for sha_shorts in fstr_dict.values():
                    target[fstr_root][fstr].update(sha_shorts)
        return target

    def fr2f2sha_set_to_list(
        self, source: dict[FileStr, dict[FileStr, set[SHAShort]]]
    ) -> dict[FileStr, dict[FileStr, list[SHAShort]]]:
        target: dict[FileStr, dict[FileStr, list[SHAShort]]] = {}
        for fstr_root, fstr_root_dict in source.items():
            target[fstr_root] = {}
            for fstr, sha_shorts in fstr_root_dict.items():
                target[fstr_root][fstr] = sorted(
                    sha_shorts, key=lambda x: self.sha_short2nr[x], reverse=True
                )
        return target

    @property
    def sha_short2nr(self) -> dict[SHAShort, int]:
        return self.repo_reader.sha_short2nr

    @property
    def nr2sha_short(self) -> dict[int, SHAShort]:
        return self.repo_reader.nr2sha_short


class StatTables:
    @staticmethod
    def get_author2fstr2fstat(
        fstrs: list[FileStr],
        fstr2commit_groups: dict[FileStr, list[CommitGroup]],
        persons_db: PersonsDB,
    ) -> dict[Author, dict[FileStr, FileStat]]:
        target: dict[Author, dict[FileStr, FileStat]] = {"*": {}}
        target["*"]["*"] = FileStat("*")
        for author in persons_db.authors_included:
            target[author] = {}
            target[author]["*"] = FileStat("*")
        # Start with last commit and go back in time
        for fstr in fstrs:
            for commit_group in fstr2commit_groups[fstr]:
                target["*"]["*"].stat.add_commit_group(commit_group)
                author = persons_db.get_author(commit_group.author)
                target[author]["*"].stat.add_commit_group(commit_group)
                if fstr not in target[author]:
                    target[author][fstr] = FileStat(fstr)
                target[author][fstr].add_commit_group(commit_group)
        return target

    @staticmethod
    def get_fstr2fstat(
        author2fstr2fstat: dict[Author, dict[FileStr, FileStat]],
        fstr2commit_group: dict[FileStr, list[CommitGroup]],
    ) -> dict[FileStr, FileStat]:
        source = author2fstr2fstat
        target: dict[FileStr, FileStat] = {}
        fstrs = set()
        for author, fstr2fstat in source.items():
            if author == "*":
                target["*"] = source["*"]["*"]
            else:
                for fstr, fstat in fstr2fstat.items():
                    if fstr != "*":
                        fstrs.add(fstr)
                        if fstr not in target:
                            target[fstr] = FileStat(fstr)
                        target[fstr].stat.add(fstat.stat)
        for fstr in fstrs:
            for commit_group in fstr2commit_group[fstr]:
                # Order of names must correspond to the order of the commits
                target[fstr].add_name(commit_group.fstr)
        return target

    @staticmethod
    def get_fstr2author2fstat(
        author2fstr2fstat: dict[Author, dict[FileStr, FileStat]],
    ) -> dict[Author, dict[FileStr, FileStat]]:
        source = author2fstr2fstat
        target: dict[FileStr, dict[Author, FileStat]] = {}
        for author, fstr2fstat in source.items():
            if author == "*":
                target["*"] = source["*"]
                continue
            for fstr, fstat in fstr2fstat.items():
                if fstr == "*":
                    continue
                if fstr not in target:
                    target[fstr] = {}
                    target[fstr]["*"] = FileStat(fstr)
                target[fstr][author] = fstat
                target[fstr]["*"].stat.add(fstat.stat)
                target[fstr]["*"].names = fstr2fstat[fstr].names
        return target

    @staticmethod
    def get_author2pstat(
        author2fstr2fstat: dict[Author, dict[FileStr, FileStat]], persons_db: PersonsDB
    ) -> dict[Author, PersonStat]:
        source = author2fstr2fstat
        target: dict[Author, PersonStat] = {}
        for author, fstr2fstat in source.items():
            if author == "*":
                target["*"] = PersonStat(Person("*", "*"))
                target["*"].stat = source["*"]["*"].stat
                continue
            target[author] = PersonStat(persons_db.get_person(author))
            for fstr, fstat in fstr2fstat.items():
                if fstr == "*":
                    continue
                target[author].stat.add(fstat.stat)
        return target

    AuthorOrFileStr = TypeVar("AuthorOrFileStr", Author, FileStr)
    PersonStatOrFileStat = TypeVar("PersonStatOrFileStat", PersonStat, FileStat)

    @staticmethod
    def calculate_percentages(
        af2pf_stat: dict[AuthorOrFileStr, PersonStatOrFileStat],
        total_insertions: int,
        total_lines: int,
    ) -> None:
        """
        Calculate the percentage of insertions and lines for each author or file.
        The percentages are stored in the stat objects from the af2pf_stat dictionary.
        This dictionary is edited in place and serves as input and output.
        """
        for af in af2pf_stat.keys():  # af is either an author or fstr
            af2pf_stat[af].stat.percent_insertions = divide_to_percentage(
                af2pf_stat[af].stat.insertions, total_insertions
            )
            af2pf_stat[af].stat.percent_lines = divide_to_percentage(
                af2pf_stat[af].stat.line_count, total_lines
            )


def get_repos(dir_path: Path, depth: int) -> list[list[GIRepo]]:
    """
    Recursively retrieves a list of repositories from a given directory path up to a
    specified depth.

    Args:
        - dir_path (Path): The directory path to search for repositories.
        - depth (int): The depth of recursion to search for repositories. A depth of 0
          means only the given directory is checked.

    Returns:
        list[list[GIRepo]]: A list of lists, where each inner list contains repositories
        found in the same directory.

    Notes:
        - If the given path is not a directory, an empty list is returned.
        - If the given path is a Git repository, a list containing a single list with
          one GIRepo object is returned.
        - If the depth is greater than 0, the function will recursively search
          subdirectories for Git repositories.
    """
    repo_lists: list[list[GIRepo]]
    if is_dir_safe(dir_path):
        if is_git_repo(dir_path):
            return [[GIRepo(dir_path.name, dir_path)]]  # independent of depth
        elif depth == 0:
            # For depth == 0, the input itself must be a repo, which is not the case.
            return []
        else:  # depth >= 1:
            subdirs: list[Path] = subdirs_safe(dir_path)
            repos: list[GIRepo] = [
                GIRepo(subdir.name, subdir) for subdir in subdirs if is_git_repo(subdir)
            ]
            repos = sorted(repos, key=lambda x: x.name)
            other_dirs: list[Path] = [
                subdir for subdir in subdirs if not is_git_repo(subdir)
            ]
            other_dirs = sorted(other_dirs)
            repo_lists = [repos] if repos else []
            for other_dir in other_dirs:
                repo_lists.extend(get_repos(other_dir, depth - 1))
            return repo_lists
    else:
        log(f"Path {dir_path} is not a directory")
        return []


def is_dir_safe(path: Path) -> bool:
    try:
        return os.path.isdir(path)
    except PermissionError:
        logger.warning(f"Permission denied for path {str(path)}")
        return False


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
        repo = Repository(str(path))
        return not repo.is_bare
    except (KeyError, ValueError, OSError):
        return False


def subdirs_safe(path: Path) -> list[Path]:
    try:
        if not is_dir_safe(path):
            return []
        subs: list[FileStr] = os.listdir(path)
        sub_paths = [path / sub for sub in subs]
        return [path for path in sub_paths if is_dir_safe(path)]
    # Exception when the os does not allow to list the contents of the path dir:
    except PermissionError:
        logger.warning(f"Permission denied for path {str(path)}")
        return []


def total_len(repo_lists: list[list[GIRepo]]) -> int:
    return sum(len(repo_list) for repo_list in repo_lists)
