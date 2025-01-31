import platform


def close_tab_key():
    return "⌘+W" if platform.system() == "Darwin" else "Ctrl+W"


def close_browser_key():
    match platform.system():
        case "Darwin":
            return "⌘+Q"
        case "Linux":
            return "Ctrl+Q"
        case "Windows":
            return "Alt+F4"
        case _:
            return "Ctrl+Q"


CLOSE_OUTPUT_VIEWERS_MSG = (
    f"To continue, close the browser window ({close_browser_key()}), or the browser "
    f"tab(s) ({close_tab_key()}) once the pages have fully loaded."
)
CLOSE_OUTPUT_VIEWERS_CLI_MSG = CLOSE_OUTPUT_VIEWERS_MSG + " Use Ctrl+C if necessary."
