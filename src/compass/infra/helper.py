def format_github_handle(github_handle: str) -> str:
    formatted_handle = github_handle.replace("https://github.com/", "")
    formatted_handle = formatted_handle.replace("http://github.com/", "")
    formatted_handle = formatted_handle.replace("github.com/", "")
    formatted_handle = formatted_handle.replace("@", "")
    return formatted_handle.lower()
