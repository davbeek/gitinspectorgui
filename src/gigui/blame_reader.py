from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from git import Commit as GitCommit
from git import GitCommandError, Repo

from gigui.args_settings import STATIC, Args
from gigui.comment import get_is_comment_lines
from gigui.data import FileStat, PersonsDB
from gigui.typedefs import (
    Author,
    BlameLines,
    Email,
    FileStr,
    GitBlames,
    SHALong,
    SHAShort,
)
from gigui.utils import log


# Commit that is used to order and number commits by date, starting at 1 for the
# initial commit.
@dataclass
class Commit:
    sha_short: SHAShort
    sha_long: SHALong
    date: int


@dataclass
class Blame:
    author: Author
    email: Email
    date: datetime
    message: str
    sha_long: SHALong
    commit_nr: int
    is_comment_lines: list[bool]
    lines: BlameLines


class BlameBaseReader:
    args: Args

    def __init__(
        self,
        git_repo: Repo,
        ex_sha_shorts: set[SHAShort],
        all_fstrs: list[FileStr],
        fstrs: list[FileStr],
        fstr2fstat: dict[FileStr, FileStat],
        persons_db: PersonsDB,
    ):
        self.git_repo = git_repo
        self.ex_sha_shorts = ex_sha_shorts

        # Unfiltered list of files, may still include files that belong completely to an
        # excluded author.
        self.all_fstrs = all_fstrs

        # List of files in repo module with complete filtering, so no files that belong
        # to excluded authors.
        self.fstrs = fstrs
        self.fstr2fstat: dict[FileStr, FileStat] = fstr2fstat
        self.persons_db = persons_db

        # List of blame authors, so no filtering, ordered by highest blame line count.
        self.blame_authors: list[Author] = []

        self.fstr2blames: dict[FileStr, list[Blame]] = {}

        # Set of all commit SHAs to commit numbers. The commits have been added in
        # reverse order, so starting with the initial commit with nr 1.
        self.sha2nr: dict[SHALong, int] = {}
        self.fstr2names: dict[FileStr, list[FileStr]] = {}
        self._set_sha2nr()
        self._set_fstr2names()

    # Need to number the complete list of all commits, because even when --since
    # severely restricts the number of commits to analyse, the result of git blame
    # always needs a commit that changed the file in question, even when there is no
    # such commit that satisfies the --since criterion.
    def _set_sha2nr(self) -> None:
        c: GitCommit
        i: int
        commits = list(self.git_repo.iter_commits())
        i = len(commits)
        for c in commits:
            self.sha2nr[c.hexsha] = i
            i -= 1

    def _set_fstr2names(self):
        for fstr in self.fstrs:
            names = self.fstr2fstat[fstr].names[:]  # make a copy]
            if not names or not names[0] == fstr:
                names.insert(0, fstr)
            self.fstr2names[fstr] = names

    def _get_git_blames_for(
        self, fstr: FileStr, root_sha: SHALong
    ) -> tuple[GitBlames, FileStr]:
        copy_move_int2opts: dict[int, list[str]] = {
            0: [],
            1: ["-M"],
            2: ["-C"],
            3: ["-C", "-C"],
            4: ["-C", "-C", "-C"],
        }
        blame_opts: list[str] = copy_move_int2opts[self.args.copy_move]
        if self.args.since:
            blame_opts.append(f"--since={self.args.since}")
        if not self.args.whitespace:
            blame_opts.append("-w")
        for rev in self.ex_sha_shorts:
            blame_opts.append(f"--ignore-rev={rev}")
        working_dir = self.git_repo.working_dir
        ignore_revs_path = Path(working_dir) / "_git-blame-ignore-revs.txt"
        if ignore_revs_path.exists():
            blame_opts.append(f"--ignore-revs-file={str(ignore_revs_path)}")

        # Run the git command to get the blames for the file.
        git_blames: GitBlames = self._run_git_command(root_sha, fstr, blame_opts)
        return git_blames, fstr

    def _process_git_blames(self, fstr: FileStr, git_blames: GitBlames) -> list[Blame]:
        blames: list[Blame] = []
        dot_ext = Path(fstr).suffix
        extension = dot_ext[1:] if dot_ext else ""
        in_multi_comment = False
        for b in git_blames:  # type: ignore
            if not b:
                continue
            c: GitCommit = b[0]  # type: ignore

            author = c.author.name  # type: ignore
            email = c.author.email  # type: ignore
            self.persons_db.add_person(author, email)

            nr = self.sha2nr[c.hexsha]  # type: ignore
            lines: BlameLines = b[1]  # type: ignore
            is_comment_lines: list[bool]
            is_comment_lines, _ = get_is_comment_lines(
                extension, lines, in_multi_comment
            )
            blame: Blame = Blame(
                author,  # type: ignore
                email,  # type: ignore
                c.committed_datetime,  # type: ignore
                c.message,  # type: ignore
                c.hexsha,  # type: ignore
                nr,  # commit number
                is_comment_lines,
                lines,  # type: ignore
            )
            blames.append(blame)
        return blames

    def _run_git_command(
        self,
        root_sha: SHALong,
        fstr: FileStr,
        blame_opts: list[str],
    ) -> GitBlames:
        git_blames: GitBlames = self.git_repo.blame(
            root_sha, fstr, rev_opts=blame_opts
        )  # type: ignore
        return git_blames


class BlameReader(BlameBaseReader):
    def __init__(self, head_sha: SHALong, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.head_sha: SHALong = head_sha

    # Set the fstr2blames dictionary, but also add the author and email of each
    # blame to the persons list. This is necessary, because the blame functionality
    # can have another way to set/get the author and email of a commit.
    def run(self, thread_executor: ThreadPoolExecutor) -> None:
        git_blames: GitBlames
        blames: list[Blame]

        self._set_fstr2names()

        if self.args.multi_thread:
            futures = [
                thread_executor.submit(self._get_git_blames_for, fstr, self.head_sha)
                for fstr in self.all_fstrs
            ]
            for future in as_completed(futures):
                git_blames, fstr = future.result()
                blames = self._process_git_blames(fstr, git_blames)
                self.fstr2blames[fstr] = blames
        else:  # single thread
            for fstr in self.all_fstrs:
                git_blames, fstr = self._get_git_blames_for(fstr, self.head_sha)
                blames = self._process_git_blames(fstr, git_blames)
                self.fstr2blames[fstr] = blames  # type: ignore

        # New authors and emails may have been found in the blames, so update
        # the authors of the blames with the possibly newly found persons
        fstr2blames: dict[FileStr, list[Blame]] = {}
        for fstr in self.all_fstrs:
            # fstr2blames will be the new value of self.fstr2blames
            fstr2blames[fstr] = []
            for blame in self.fstr2blames[fstr]:
                # update author
                blame.author = self.persons_db.get_author(blame.author)
                fstr2blames[fstr].append(blame)
        self.fstr2blames = fstr2blames

    def update_author2fstr2fstat(
        self, author2fstr2fstat: dict[Author, dict[FileStr, FileStat]]
    ) -> dict[Author, dict[FileStr, FileStat]]:
        """
        Update author2fstr2fstat with line counts for each author.
        Set local list of sorted unfiltered _blame_authors.
        """
        author2line_count: dict[Author, int] = {}
        target = author2fstr2fstat
        for fstr in self.all_fstrs:
            blames = self.fstr2blames[fstr]
            for b in blames:
                person = self.persons_db.get_person(b.author)
                author = person.author
                if author not in author2line_count:
                    author2line_count[author] = 0
                total_line_count = len(b.lines)  # type: ignore
                comment_lines_subtract = (
                    0 if self.args.comments else b.is_comment_lines.count(True)
                )
                empty_lines_subtract = (
                    0
                    if self.args.empty_lines
                    else len([line for line in b.lines if not line.strip()])
                )
                line_count = (
                    total_line_count - comment_lines_subtract - empty_lines_subtract
                )
                author2line_count[author] += line_count
                if not person.filter_matched:
                    if fstr not in target[author]:
                        target[author][fstr] = FileStat(fstr)
                    target[author][fstr].stat.line_count += line_count  # type: ignore
                    target[author]["*"].stat.line_count += line_count
                    target["*"]["*"].stat.line_count += line_count
        return target


class BlameHistoryReader(BlameBaseReader):
    args: Args

    # pylint: disable=too-many-arguments disable=too-many-positional-arguments
    def __init__(
        self,
        fstr2blames: dict[FileStr, list[Blame]],
        fstr2shas: dict[FileStr, list[SHALong]],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fstr2blames: dict[FileStr, list[Blame]] = fstr2blames
        self.fstr2shas: dict[FileStr, list[SHALong]] = fstr2shas

        # Dict from a file to all its previous names (due to renaming) in the repo
        self.fstr2names: dict[FileStr, list[FileStr]] = {}

        self.fstr2sha2blames: dict[FileStr, dict[SHALong, list[Blame]]] = {}
        self.run()

    def run(self) -> None:
        git_blames: GitBlames
        blames: list[Blame]

        self._set_fstr2names()

        if self.args.blame_history == STATIC:
            for fstr in self.fstrs:
                head_sha = self.fstr2shas[fstr][0]
                self.fstr2sha2blames[fstr] = {}
                self.fstr2sha2blames[fstr][head_sha] = self.fstr2blames[fstr]
                shas = self.fstr2shas[fstr]
                for sha in shas:
                    if not self.fstr2names[fstr]:
                        break
                    git_blames, _ = self._get_git_blames_for(fstr, sha)
                    blames = self._process_git_blames(fstr, git_blames)
                    self.fstr2sha2blames[fstr][sha] = blames

        # Assume that no new authors are found when using earlier root commit_shas, so
        # do not update authors of the blames with the possibly newly found persons as
        # in BlameReader.run().

    def _run_git_command(
        self,
        root_sha: SHALong,
        fstr: FileStr,
        blame_opts: list[str],
    ) -> GitBlames:
        while True:
            try:
                fstr_name = self.fstr2names[fstr][0]
                git_blames: GitBlames = self.git_repo.blame(
                    root_sha, fstr_name, rev_opts=blame_opts
                )  # type: ignore
                break  # Exit the loop if no exception is raised
            except GitCommandError:
                self.fstr2names[fstr].pop(0)
                if not self.fstr2names[fstr]:
                    log(f"GitCommandError for blame of file {fstr}, sha {root_sha}")
                    return [[]]
        return git_blames

    def generate_blame_history(self, fstr: FileStr, sha: SHALong) -> list[Blame]:
        git_blames: GitBlames
        git_blames, _ = self._get_git_blames_for(fstr, sha)
        blames: list[Blame] = self._process_git_blames(fstr, git_blames)
        return blames
