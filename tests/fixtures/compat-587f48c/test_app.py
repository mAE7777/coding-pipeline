import os
import tempfile

import app

assert app.show([]) == "(empty)"

os.environ["LIST_FILE"] = os.path.join(tempfile.mkdtemp(), "list.txt")
app.main(["add", "milk"])
app.main(["add", "eggs"])
assert app.load() == ["milk", "eggs"], app.load()
assert app.show(app.load()) == "1. milk\n2. eggs"
print("tests ok")
