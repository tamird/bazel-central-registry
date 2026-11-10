"""Compare the default VM and bytecode layout before and after the x64 default changed."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from urllib.request import urlopen

registry = Path.cwd()
revision = "3f7de0143267b139a2a3ba67ffab037ff4f0b7fc"
assert subprocess.check_output(["git", "rev-parse", "HEAD^"], text=True).strip() == revision
assert platform.system() == "Linux" and platform.machine() == "x86_64"
output = Path(os.environ["RUNNER_TEMP"]) / "luajit-gc64.json"
result = {"registry": revision, "os": platform.platform(), "cases": []}
output.write_text(json.dumps(result, indent=2))
probe = """local f=require('ffi'); local b=string.dump(function() return 17 end)
local gc=f.abi('gc64'); local fr2=bit.band(b:byte(5),8)~=0
assert(jit.arch=='x64' and jit.status() and fr2==gc)
assert(assert(loadstring(b))()==17)
print(jit.version..' gc64='..tostring(gc)..' fr2='..tostring(fr2))"""

with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as tmp:
    work = Path(tmp)
    bazel = work / "bazel"
    url = "https://releases.bazel.build/9.3.1/release/bazel-9.3.1-linux-x86_64"
    with urlopen(url, timeout=60) as resp:
        bazel.write_bytes(resp.read())
    assert hashlib.sha256(bazel.read_bytes()).hexdigest() == "7f775b54bbec487efaf0f49ccda1d2ed02cd34f582edfdd6aeeec76e39ef585c"
    bazel.chmod(0o755)
    failed = []
    for version, options, expected in [
        ("2.1.0-beta3", [], False),
        ("2.1.1794214635", [], True),
        ("2.1.1794214635", ["--@luajit//:gc64=false"], False),
    ]:
        (work / "MODULE.bazel").write_text(f'module(name = "consumer")\nbazel_dep(name = "luajit", version = "{version}")\n')
        (work / "BUILD.bazel").touch()
        cmd = [str(bazel), "--nosystem_rc", "--nohome_rc", "run", "--registry=" + registry.as_uri(),
               "--registry=https://bcr.bazel.build", "--lockfile_mode=off", "--jobs=4", *options,
               "@luajit//:bin/luajit", "--", "-e", probe]
        proc = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = proc.stdout.splitlines()
        value = str(expected).lower()
        expected_line = f"LuaJIT {version} gc64={value} fr2={value}"
        row = {"module": version, "options": options, "expected": expected_line,
               "exit": proc.returncode, "cli": [line for line in lines if line.startswith("LuaJIT ")]}
        if proc.returncode or expected_line not in lines:
            failed.append(row)
            row["diagnostics"] = lines[-20:]
        result["cases"].append(row)
        output.write_text(json.dumps(result, indent=2))
        print(json.dumps(row), flush=True)
    if failed:
        raise SystemExit(1)
