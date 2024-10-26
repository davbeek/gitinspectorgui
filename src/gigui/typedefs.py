from git import Commit as GitCommit

type Author = str  # type: ignore
type Email = str  # type: ignore
type FileStr = str  # type: ignore
type FilePattern = str  # type: ignore
type Row = list[str | int | float]  # type: ignore

type SHALong = str  # type: ignore  # long commit SHA
type SHAShort = str  # type: ignore # short commit SHA
type Rev = SHALong | SHAShort  # type: ignore  # long or short commit SHA

type Html = str  # type: ignore

type BlameLine = str  # type: ignore # single line of code
type BlameLines = list[BlameLine]  # type: ignore
# GitBlames is a list of two-element lists
# Each two-element list contains a GitCommit followed by a list of Blame lines
type GitBlames = list[list[GitCommit | BlameLines]]  # type: ignore

type RowsBools = tuple[list[Row], list[bool]]  # type: ignore
