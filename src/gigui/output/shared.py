from collections import Counter
from math import isnan
from typing import Any

from gigui.data import FileStat, PersonStat, Stat
from gigui.repo import GIRepo
from gigui.typedefs import Author, FileStr, Row

deletions: bool = False
scaled_percentages: bool = False
subfolder: str = ""


def header_stat() -> list[str]:
    return [
        "% Lines",
        "% Insertions",
        "Lines",
        "Insertions",
        "Stability",
        "Commits",
    ] + (["Deletions", "Age Y:M:D"] if deletions else ["Age Y:M:D"])


def header_authors(html: bool = True) -> list[str]:
    header_prefix = ["ID", "Author"] + (["Empty", "Email"] if html else ["Email"])
    if scaled_percentages:
        return (
            header_prefix
            + [
                "% Lines",
                "% Insertions",
                "% Scaled Lines",
                "% Scaled Insertions",
                "Lines",
                "Insertions",
                "Stability",
                "Commits",
            ]
            + (["Deletions", "Age"] if deletions else ["Age"])
        )
    else:
        return header_prefix + header_stat()


def header_authors_files(html: bool = True) -> list[str]:
    header_prefix = ["ID", "Author"] + (["Empty", "File"] if html else ["File"])
    return header_prefix + header_stat()


def header_files_authors(html: bool = True) -> list[str]:
    header_prefix = ["ID", "File"] + (["Empty", "Author"] if html else ["Author"])
    return header_prefix + header_stat()


def header_files() -> list[str]:
    return ["ID", "File"] + header_stat()


def header_blames() -> list[str]:
    return [
        "ID",
        "Author",
        "Date",
        "Message",
        "SHA",
        "Commit number",
        "Line",
        "Code",
    ]


def percentage_to_out(percentage: float) -> int | str:
    if isnan(percentage):
        return ""
    else:
        return round(percentage)


class RowTable:
    def __init__(self, repo: GIRepo):
        self.repo = repo
        self.rows: list[Row] = []

    # Return a sorted list of authors occurring in the stats outputs, so these are
    # filtered authors.
    def get_authors_included(self) -> list[Author]:
        a2p: dict[Author, PersonStat] = self.repo.author2pstat
        authors = list(a2p.keys())
        authors = sorted(authors, key=lambda x: a2p[x].stat.line_count, reverse=True)
        return authors

    def _get_stat_values(self, stat: Stat, nr_authors: int = 2) -> list[Any]:
        return (
            [
                percentage_to_out(stat.percent_lines),
                percentage_to_out(stat.percent_insertions),
            ]
            + (
                [
                    percentage_to_out(stat.percent_lines * nr_authors),
                    percentage_to_out(stat.percent_insertions * nr_authors),
                ]
                if scaled_percentages
                else []
            )
            + [
                stat.line_count,
                stat.insertions,
                stat.stability,
                len(stat.commits),
            ]
            + ([stat.deletions, stat.age] if self.repo.args.deletions else [stat.age])
        )


class AuthorsRowTable(RowTable):
    def get_rows(self, html: bool = True) -> list[Row]:
        a2p: dict[Author, PersonStat] = self.repo.author2pstat
        row: Row
        rows: list[Row] = []
        id_val: int = 0
        for author in self.get_authors_included():
            person = self.repo.get_person(author)
            row = [id_val, person.authors_str] + (
                ["", person.emails_str] if html else [person.emails_str]
            )  # type: ignore
            row.extend(self._get_stat_values(a2p[author].stat, len(a2p)))
            rows.append(row)
            id_val += 1
        return rows


class AuthorsFilesRowTable(RowTable):
    def get_rows(self, html: bool = True) -> list[Row]:
        a2f2f: dict[Author, dict[FileStr, FileStat]] = self.repo.author2fstr2fstat
        row: Row
        rows: list[Row] = []
        id_val: int = 0
        for author in self.get_authors_included():
            person = self.repo.get_person(author)
            fstrs = list(a2f2f[author].keys())
            fstrs = sorted(
                fstrs,
                key=lambda x: self.repo.fstr2fstat[x].stat.line_count,
                reverse=True,
            )
            for fstr in fstrs:
                row = []
                rel_fstr = a2f2f[author][fstr].relative_names_str(subfolder)
                row.extend(
                    [id_val, person.authors_str]
                    + (["", rel_fstr] if html else [rel_fstr])  # type: ignore
                )
                stat = a2f2f[author][fstr].stat
                row.extend(self._get_stat_values(stat))
                rows.append(row)
            id_val += 1
        return rows


class FilesAuthorsRowTable(RowTable):
    def get_rows(self, html: bool = True) -> list[Row]:
        f2a2f: dict[FileStr, dict[Author, FileStat]] = self.repo.fstr2author2fstat
        row: Row
        rows: list[Row] = []
        id_val: int = 0
        fstrs = list(f2a2f.keys())
        fstrs = sorted(
            fstrs,
            key=lambda x: self.repo.fstr2fstat[x].stat.line_count,
            reverse=True,
        )
        for fstr in fstrs:
            authors = list(f2a2f[fstr].keys())
            authors = sorted(
                authors,
                key=lambda x: f2a2f[fstr][  # pylint: disable=cell-var-from-loop
                    x
                ].stat.line_count,
                reverse=True,
            )
            for author in authors:
                row = []
                authors_str = self.repo.get_person(author).authors_str
                row.extend(
                    [id_val, f2a2f[fstr][author].relative_names_str(subfolder)]
                    + (["", authors_str] if html else [authors_str])  # type: ignore
                )
                stat = f2a2f[fstr][author].stat
                row.extend(self._get_stat_values(stat))
                rows.append(row)
            id_val += 1
        return rows


class FilesRowTable(RowTable):
    def get_rows(self) -> list[Row]:
        f2f: dict[FileStr, FileStat] = self.repo.fstr2fstat
        rows: list[Row] = []
        row: Row
        id_val: int = 0
        for fstr in self.repo.sorted_star_fstrs:
            row = [id_val, f2f[fstr].relative_names_str(subfolder)]
            row.extend(self._get_stat_values(f2f[fstr].stat))
            rows.append(row)
            id_val += 1
        return rows


def get_blames(repo: GIRepo, html: bool) -> dict[FileStr, tuple[list[Row], list[bool]]]:
    return repo.blame_tables.get_fstr2blame_rows(html)  # type: ignore


def string2truncated(orgs: list[str], max_length: int) -> dict[str, str]:

    def get_trunc2digits(org2trunc: dict[str, str]) -> dict[str, int]:
        count: Counter[str] = Counter(org2trunc.values())

        # If truncated value is unique, it does not need to be numbered and its nr of
        # digit are 0. If it is not unique and occurs n times, then digits is the number
        # of digits in the string repr of n.
        digits: dict[str, int] = {}
        for org in org2trunc:
            if count[org2trunc[org]] == 1:
                digits[org] = 0
            else:
                digits[org] = len(str(count[org2trunc[org]]))
        return digits

    # Precondition: All values of org2trunc are already shortened to max_length - 2 for
    # ".." prefix.
    # Shorten all values of org2trunc so that they can be prefixed with ".." and
    # postfixed with a number "-n" to make them unique.
    def truncate(org2trunc: dict[str, str]) -> dict[str, str]:
        # Take Count for org2trunc values. For each item org, trunc in org2trunc, if
        # trunc has a count value > 1, shorten to the required length by removing the
        # necessary characters. If trunc has a count of 1, keep it as is.
        count: Counter[str] = Counter(org2trunc.values())
        trunc2digits: dict[str, int] = get_trunc2digits(org2trunc)
        result = {}
        for org in org2trunc:
            if count[org2trunc[org]] > 1:
                n_digits = trunc2digits[org]
                # n_digits for number and 3 for ".." prefix and "-" suffix:
                required_length = max_length - n_digits - 3
                reduce_by = len(org2trunc[org]) - required_length
                if reduce_by > 0:
                    result[org] = org2trunc[org][reduce_by:]
                else:
                    result[org] = org2trunc[org]
            else:
                result[org] = org2trunc[org]
        return result

    def number(org2trunc: dict[str, str]) -> dict[str, str]:
        # Add ".." prefix and "-n" suffix if necessary.
        # Number each duplicate in org2trunc.values() sequentially
        count: Counter[str] = Counter(org2trunc.values())
        seen2i: dict[str, int] = {}
        result = {}
        for org in org2trunc:
            if count[org2trunc[org]] > 1:
                if org2trunc[org] in seen2i:
                    seen2i[org2trunc[org]] += 1
                else:
                    seen2i[org2trunc[org]] = 1
                result[org] = f"..{org2trunc[org]}-{seen2i[org2trunc[org]]}"
            else:
                result[org] = f"..{org2trunc[org]}"
        return result

    org_short: list[str] = []
    org2trunc: dict[str, str] = {}

    # Add strings < max_length chars to org_short, truncate others to max_length - 2 by
    # removing chars from the beginning
    for org in orgs:
        if len(org) <= max_length:
            org_short.append(org)
        else:
            org2trunc[org] = org[(len(org) - max_length) + 2 :]

    new_org2trunc = truncate(org2trunc)
    while new_org2trunc != org2trunc:
        org2trunc = new_org2trunc
        new_org2trunc = truncate(org2trunc)

    # Add prefix and postfix to truncated strings.
    org2trunc = number(org2trunc)

    for trunc in org2trunc.values():
        assert len(trunc) == max_length

    # Add strings < max_length chars to org2trunc
    for org in org_short:
        org2trunc[org] = org

    missing = set(orgs) - set(org2trunc.keys())
    extra = set(org2trunc.keys()) - set(orgs)
    assert len(extra) == 0
    assert len(missing) == 0

    for trunc in org2trunc.values():
        assert len(trunc) <= max_length

    # # Visually check that numbering has been done correctly
    # numbered = {trunc for trunc in org2trunc.values() if trunc[-1].isdigit()}
    # numbered = sorted(numbered)
    # for trunc in numbered:
    #     print(trunc)

    return org2trunc
