import sys
from pathlib import Path

from xlsxwriter import Workbook
from xlsxwriter.chart import Chart
from xlsxwriter.workbook import Format as ExcelFormat
from xlsxwriter.worksheet import Worksheet

from gigui.output.outbase import (
    TableStatsRows,
    header_authors,
    header_authors_files,
    header_blames,
    header_files,
    header_files_authors,
    string2truncated,
)
from gigui.typedefs import FileStr, Row
from gigui.utils import get_relative_fstr

type FormatSpec = dict[str, str | int | float]

MAX_LENGTH_SHEET_NAME = 31  # hard coded in Excel

# Same for row and blame colors
# Note that not specifying a color is equivalent to specifying white
WHITE = "#FFFFFF"

# Author background colors
AUTHOR_LIGHT_GREEN = "#E6FFE6"
AUTHOR_LIGHT_BLUE = "#ADD8E6"
AUTHOR_LIGHT_RED = "#FFCCCB"
AUTHOR_LIGHT_YELLOW = "#FFFFBF"
AUTHOR_LIGHT_ORANGE = "#FFD7B5"
AUTHOR_LIGHT_PURPLE = "#CBC3E3"
AUTHOR_LIGHT_GRAY = "#D3D3D3"

# Row background and border colors
ROW_WHITE_BORDER = "#D8E4BC"

ROW_LIGHT_GREEN = "#EBF1DE"
ROW_LIGHT_GREEN_BORDER = "C4D79B"

# Worksheet zoom level for macOS is 120, for other platforms 100
ZOOM_LEVEL = 120 if sys.platform == "darwin" else 100


class Sheet:
    def __init__(
        self,
        worksheet: Worksheet,
        book: "Book",
    ):
        self.worksheet: Worksheet = worksheet
        self.book: "Book" = book
        self.formats: dict[str, ExcelFormat] = book.formats

        self.row: int = 0
        self.col: int = 0
        self.max_row: int = 0
        self.max_col: int = 0

        worksheet.set_zoom(ZOOM_LEVEL)

    def set_pos(self, row: int, col: int) -> None:
        self.row = row
        self.col = col

    def inc_row(self) -> None:
        self.row += 1

    def inc_col(self) -> None:
        self.col += 1

    def reset_col(self) -> None:
        self.col = 0

    def next_row(self) -> None:
        self.inc_row()
        self.reset_col()

    def update_max(self, row: int, col: int) -> None:
        self.max_row = max(self.max_row, row)
        self.max_col = max(self.max_col, col)

    def write(self, data, excel_format: ExcelFormat | None = None) -> None:
        self.worksheet.write(self.row, self.col, data, excel_format)
        self.update_max(self.row, self.col)
        self.inc_col()

    def write_number(self, n: int) -> None:
        self.worksheet.write_number(self.row, self.col, n)
        self.update_max(self.row, self.col)
        self.inc_col()

    def write_string(self, s: str) -> None:
        self.worksheet.write_string(self.row, self.col, s)
        self.update_max(self.row, self.col)
        self.inc_col()

    def write_row(
        self, data_list: list, excel_format: ExcelFormat | None = None
    ) -> None:
        data_list = [data for data in data_list if data is not None]
        if data_list:
            self.worksheet.write_row(self.row, self.col, data_list, excel_format)
            new_col = self.col + len(data_list) - 1
            self.update_max(self.row, new_col)
            self.set_pos(self.row, new_col + 1)

    def number_to_letter(self, n: int) -> str:
        return chr(ord("A") + n)


class TableSheet(Sheet):
    def __init__(
        self,
        header_items: list[str],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.header_items: list[str] = header_items

        self.head2col: dict[str, int] = {}
        self.head2format_name: dict[str, str] = {}
        self.head2width: dict[str, int] = {}

        self.worksheet.set_zoom(ZOOM_LEVEL)
        self.head2width |= {
            "ID": 4,
        }
        self.head2format_name["ID"] = "align_left"

    def create_header(self) -> list[dict[str, str]]:
        head_list = self.header_items
        header = [({"header": head}) for head in head_list]
        for col, head in enumerate(head_list):
            self.head2col[head] = col
        return header

    def head_to_letter(self, head: str) -> str:
        col = self.head2col[head]
        return self.number_to_letter(col)

    def set_excel_column_formats(self) -> None:
        for head in self.header_items:
            col = self.head2col[head]
            width = self.head2width.get(head)
            format_name = self.head2format_name.get(head)
            excel_format = self.formats.get(format_name)  # type: ignore
            self.worksheet.set_column(col, col, width, excel_format)

    def add_table(self, header: list[dict[str, str]]) -> None:
        self.worksheet.add_table(
            0,
            0,
            self.max_row,
            self.max_col,
            {
                "columns": header,
                "style": "Table Style Light 11",
            },
        )
        self.worksheet.freeze_panes(1, 0)  # freeze top row

    def set_conditional_author_formats(self) -> None:
        author_color_formats: list[ExcelFormat] = self.book.author_color_formats
        # Add conditional formats for author colors
        total_formats_1 = len(author_color_formats) - 1
        for i, color_format in enumerate(author_color_formats):
            if i < total_formats_1:
                critical = "$A2=" + str(i + 1)
            else:
                # If the number of authors equals or surpasses the number of colors, the
                # last color is used for all authors with a number greater or equal to
                # the number of colors
                critical = "$A2>=" + str(i + 1)

            # Add a conditional format for each color
            # The conditional format will match the author number in the first column
            # with the corresponding color format
            self.worksheet.conditional_format(
                1,
                0,
                self.max_row,
                self.max_col,
                {
                    "type": "formula",
                    "criteria": critical,
                    "format": color_format,
                },
            )


class StatsSheet(TableSheet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.head2width |= {
            "Author": 20,
            "File": 20,
        }
        self.head2format_name |= {
            "% Lines": "num_format",
            "% Insertions": "num_format",
            "% Scaled Lines": "num_format",
            "% Scaled Insertions": "num_format",
            "Stability": "num_format",
            "Age Y:M:D": "align_right",
        }

    def set_conditional_file_formats(self) -> None:
        self.worksheet.conditional_format(
            1,
            0,
            self.max_row,
            self.max_col,
            {
                "type": "formula",
                "criteria": "MOD($A2,2)=1",
                "format": self.formats["row_white"],
            },
        )
        self.worksheet.conditional_format(
            1,
            0,
            self.max_row,
            self.max_col,
            {
                "type": "formula",
                "criteria": "MOD($A2,2)=0",
                "format": self.formats["row_light_green"],
            },
        )


class AuthorsSheet(StatsSheet):
    def __init__(self, rows: list[Row], chart: Chart, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.head2width |= {
            "Email": 20,
        }

        header = self.create_header()
        self.next_row()
        for row in rows:
            self.write_row(row)
            self.next_row()
        self.add_table(header)
        self.set_excel_column_formats()
        self.set_conditional_author_formats()

        points = []
        for c in self.book.author_colors:
            points.append({"fill": {"color": c}})
        author_letter = self.head_to_letter("Author")
        lines_letter = self.head_to_letter("% Lines")
        end_row = self.max_row + 1
        chart.add_series(
            {
                "categories": f"=Authors!${author_letter}$3:${author_letter}${end_row}",
                "values": f"=Authors!${lines_letter}$3:${lines_letter}${end_row}",
                "points": points,
            }
        )
        chart.set_legend({"none": True})
        self.worksheet.insert_chart(self.row + 1, 1, chart, {"x_scale": 0.6})


class AuthorsFilesSheet(StatsSheet):
    def __init__(self, rows: list[Row], *args, **kwargs):
        super().__init__(*args, **kwargs)

        header = self.create_header()
        self.next_row()
        for row in rows:
            self.write_row(row)
            self.next_row()
        self.add_table(header)
        self.set_excel_column_formats()
        self.set_conditional_author_formats()


class FilesAuthorsSheet(StatsSheet):
    def __init__(self, rows: list[Row], *args, **kwargs):
        super().__init__(*args, **kwargs)

        header = self.create_header()
        self.next_row()
        for row in rows:
            self.write_row(row)
            self.next_row()
        self.add_table(header)
        self.set_excel_column_formats()
        self.set_conditional_file_formats()


class FilesSheet(StatsSheet):
    def __init__(self, rows: list[Row], *args, **kwargs):
        super().__init__(*args, **kwargs)

        header = self.create_header()
        self.next_row()
        for row in rows:
            self.write_row(row)
            self.next_row()
        self.add_table(header)
        self.set_excel_column_formats()
        self.set_conditional_file_formats()


class BlameSheet(TableSheet):
    def __init__(
        self,
        rows_iscomments: tuple[list[Row], list[bool]],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        header = self.create_header()
        rows, is_comments = rows_iscomments
        for row, is_comment in zip(rows, is_comments):
            self.next_row()
            code_col: int = self.head2col["Code"]
            self.write_row(row[:code_col])
            if is_comment:
                self.write(row[code_col], self.formats["code_italic_format"])
            else:
                self.write(row[code_col], self.formats["code_format"])

        self.head2format_name |= {
            "Date": "date_format",
            "SHA": "SHA_format",
            "Code": "code_format",
        }
        self.head2width |= {
            "Author": 12,
            "Date": 10,
            "Message": 20,
            "Commit number": 6,
            "Line": 6,
            "Code": 120,
        }

        self.add_table(header)

        self.set_excel_column_formats()
        # Override font of Code column to default font by using default header format
        self.worksheet.write(
            0, self.head2col["Code"], "Code", self.formats["header_format"]
        )
        # Override right alignment of SHA column with left alignment for header
        self.worksheet.write(0, self.head2col["SHA"], "SHA", self.formats["align_left"])

        self.set_conditional_author_formats()


class Book:
    def __init__(
        self, name: str, out_rows: TableStatsRows, subfolder: str, blame_skip: bool
    ):
        self.name: str = name
        self.out_rows: TableStatsRows = out_rows
        self.subfolder = subfolder

        self.outfile: str = self.name + ".xlsx"
        self.workbook = Workbook(self.name + ".xlsx")
        self.formats: dict[str, ExcelFormat] = {}
        self.author_color_formats: list[ExcelFormat] = []
        self.author_colors = [
            AUTHOR_LIGHT_GREEN,
            AUTHOR_LIGHT_BLUE,
            AUTHOR_LIGHT_RED,
            AUTHOR_LIGHT_YELLOW,
            AUTHOR_LIGHT_ORANGE,
            AUTHOR_LIGHT_PURPLE,
            AUTHOR_LIGHT_GRAY,
        ]

        self.add_format("header_format", {"bold": True})

        self.add_format("align_left", {"align": "left"})
        self.add_format("align_right", {"align": "right"})

        self.add_format(
            "row_white",
            {"bg_color": WHITE, "border": 1, "border_color": ROW_WHITE_BORDER},
        )
        self.add_format(
            "row_light_green",
            {
                "bg_color": ROW_LIGHT_GREEN,
                "border": 1,
                "border_color": ROW_LIGHT_GREEN_BORDER,
            },
        )
        self.add_format(
            "num_format",
            {"num_format": "0"},
        )
        self.add_format(
            "SHA_format", {"align": "right", "font_name": "Menlo", "font_size": "9.5"}
        )

        code_format: dict[str, str | int | float] = {
            "font_name": "Menlo",
            "font_size": 9.5,
            "indent": 1,
        }
        self.add_format("code_format", code_format)
        self.add_format("code_italic_format", {**code_format, "italic": True})

        self.add_format("date_format", {"num_format": 14})

        for c in self.author_colors:
            self.author_color_formats.append(
                self.workbook.add_format(
                    {"bg_color": c, "border": 1, "border_color": "#D8E4BC"}
                )
            )

        Path(self.outfile).unlink(missing_ok=True)

        self.add_authors_sheet()
        self.add_authors_files_sheet()
        self.add_files_authors_sheet()
        self.add_files_sheet()
        if not blame_skip:
            self.add_blame_sheets()
        self.close()

    def add_format(self, format_name: str, format_spec: FormatSpec) -> None:
        excel_format = self.workbook.add_format(format_spec)
        self.formats[format_name] = excel_format

    def add_authors_sheet(self) -> None:
        rows: list[Row] = self.out_rows.get_authors_stats_rows()
        AuthorsSheet(
            rows,
            self.workbook.add_chart({"type": "pie"}),  # type: ignore
            header_authors(),
            self.workbook.add_worksheet("Authors"),
            self,
        )

    def add_authors_files_sheet(self) -> None:
        rows: list[Row] = self.out_rows.get_authors_files_stats_rows()
        AuthorsFilesSheet(
            rows,
            header_authors_files(),
            self.workbook.add_worksheet("Authors-Files"),
            self,
        )

    def add_files_authors_sheet(self) -> None:
        rows: list[Row] = self.out_rows.get_files_authors_stats_rows()
        FilesAuthorsSheet(
            rows,
            header_files_authors(),
            self.workbook.add_worksheet("Files-Authors"),
            self,
        )

    def add_files_sheet(self) -> None:
        rows: list[Row] = self.out_rows.get_files_stats_rows()
        FilesSheet(
            rows,
            header_files(),
            self.workbook.add_worksheet("Files"),
            self,
        )

    def add_blame_sheet(
        self,
        name,
        rows_iscomments: tuple[list[Row], list[bool]],
    ) -> None:
        if rows_iscomments:
            sheet_name = name.replace("/", ">")
            BlameSheet(
                rows_iscomments,
                header_blames(),
                self.workbook.add_worksheet(sheet_name),
                self,
            )

    def add_blame_sheets(
        self,
    ) -> None:
        fstr2rows_iscomments: dict[FileStr, tuple[list[Row], list[bool]]]
        fstr2rows_iscomments = self.out_rows.get_blames()

        relative_fstrs = [
            get_relative_fstr(fstr, self.subfolder)
            for fstr in fstr2rows_iscomments.keys()
        ]
        relative_fstr2truncated = string2truncated(
            relative_fstrs, MAX_LENGTH_SHEET_NAME
        )

        for fstr, rel_fstr in zip(fstr2rows_iscomments.keys(), relative_fstrs):
            self.add_blame_sheet(
                relative_fstr2truncated[rel_fstr],
                fstr2rows_iscomments[fstr],
            )

    def close(self) -> None:
        self.workbook.close()
