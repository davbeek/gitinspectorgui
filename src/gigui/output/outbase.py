from collections import Counter

deletions: bool = False
scaled_percentages: bool = False


def header_stat() -> list[str]:
    return [
        "% Lines",
        "% Insertions",
        "Lines",
        "Insertions",
        "Stability",
        "Commits",
    ] + (["Deletions", "Age Y:M:D"] if deletions else ["Age Y:M:D"])


def header_authors() -> list[str]:
    header_prefix = ["ID", "Author", "Email"]
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
            + (["", "Age"] if deletions else ["Age"])
        )
    else:
        return header_prefix + header_stat()


def header_authors_files() -> list[str]:
    return ["ID", "Author", "File"] + header_stat()


def header_files_authors() -> list[str]:
    return ["ID", "File", "Author"] + header_stat()


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
