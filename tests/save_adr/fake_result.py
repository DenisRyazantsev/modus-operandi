"""FakeResult: a stand-in for the save_adr tests' subprocess result objects."""


class FakeResult:
    returncode = 0
    stdout = ""
    stderr = ""
