"""Verify the declared library and bytecode saver on a native ARM64 builder."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from urllib.request import urlopen

source = "bfb6f63503f54c05af617bafc983dccc716eb4a2"
reg = Path.cwd()
assert subprocess.check_output(["git", "rev-parse", "HEAD^"], text=True).strip() == source
host = platform.system()
result = {"registry": source, "runner": os.environ["RUNNER_NAME"], "kernel": platform.release(),
          "arch": platform.machine(), "os": host}
assert result["arch"] in ("aarch64", "arm64")
out = Path(os.environ["RUNNER_TEMP"]) / "luajit-arm64-result.json"
out.write_text(json.dumps(result))
osname, digest = {
    "Linux": ("linux", "10ba9cb76d4ee748d274dcc2981992bb12b74a203dc41a9c2eceeb8f29359366"),
    "Darwin": ("darwin", "19c4958626e0e3a564a61c2e85eeaab97b550a30632b82341191aa61ed0ccc1b"),
}[host]
with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as tmp:
    work = Path(tmp)
    bazel = work / "bazel"
    url = f"https://releases.bazel.build/9.3.1/release/bazel-9.3.1-{osname}-arm64"
    with urlopen(url, timeout=60) as response:
        bazel.write_bytes(response.read())
    assert hashlib.sha256(bazel.read_bytes()).hexdigest() == digest
    bazel.chmod(0o755)
    (work/"MODULE.bazel").write_text('''module(name = "consumer")
bazel_dep(name = "luajit", version = "2.1.20230430")
bazel_dep(name = "rules_cc", version = "0.2.4")
bazel_dep(name = "bazel_skylib", version = "1.8.2")
''')
    (work/"BUILD.bazel").write_text('''load("@bazel_skylib//rules:run_binary.bzl", "run_binary")
load("@rules_cc//cc:cc_test.bzl", "cc_test")
run_binary(
    name = "bytecode",
    srcs = ["payload.lua", "@luajit//:src/jit/bcsave.lua"],
    outs = ["bytecode.h"],
    args = ["-b", "-t", "c", "-n", "probe", "$(execpath payload.lua)", "$(execpath bytecode.h)"],
    env = {"LUA_PATH": "$(execpath @luajit//:src/jit/bcsave.lua)"},
    tool = "@luajit//:bin/luajit",
)
cc_test(
    name = "consumer",
    srcs = ["consumer.c", ":bytecode"],
    deps = ["@luajit//:luajit"],
    linkstatic = True,
)
''')
    (work/"payload.lua").write_text('''assert(jit.arch == "arm64")
assert(jit.status() and require("ffi").abi("gc64"))
jit.opt.start("hotloop=4")
local sum = 0
for i = 1, 100000 do sum = sum + i end
assert(sum == 5000050000 and require("jit.util").traceinfo(1))
local ok, why = pcall(nativeerror)
assert(not ok and tostring(why):find("expected native error", 1, true))
return jit.os
''')
    (work/"consumer.c").write_text(r'''#include <stdio.h>
#include <string.h>
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
#include "bytecode.h"
static int nativeerror(lua_State *L) { return luaL_error(L, "expected native error"); }
int main(void) {
    lua_State *L = luaL_newstate();
    if (!L) return 1;
    luaL_openlibs(L);
    lua_register(L, "nativeerror", nativeerror);
    if (luaL_loadbuffer(L, (const char *)luaJIT_BC_probe, sizeof(luaJIT_BC_probe), "probe") || lua_pcall(L, 0, 1, 0)) {
        fprintf(stderr, "%s\n", lua_tostring(L, -1));
        return 1;
    }
    printf("embedded bytecode, native error and JIT trace passed: %s\n", lua_tostring(L, -1));
#ifdef __APPLE__
    int rc = strcmp(lua_tostring(L, -1), "OSX") != 0;
#else
    int rc = strcmp(lua_tostring(L, -1), "Linux") != 0;
#endif
    lua_close(L);
    return rc;
}
''')
    common = ["--registry="+reg.as_uri(), "--registry=https://bcr.bazel.build", "--lockfile_mode=off", "--jobs=4"]
    def run(cmd):
        outcome = subprocess.run([str(bazel), "--nosystem_rc", "--nohome_rc", *cmd[:1], *common, *cmd[1:]], cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(outcome.stdout, flush=True)
        result[cmd[0]] = {"exit": outcome.returncode, "log": outcome.stdout[-4000:]}
        out.write_text(json.dumps(result, indent=2))
        outcome.check_returncode()
    run(["build", "@luajit//...", "@luajit//:COPYRIGHT", "@luajit//:src/jit/bcsave.lua"])
    run(["test", "--nocache_test_results", "--flaky_test_attempts=1", "--test_output=all", "//:consumer"])
    log = (work/"bazel-testlogs/consumer/test.log").read_text()
    assert "embedded bytecode, native error and JIT trace passed: " in log
    result["testLog"] = log
    result["bytecodeSha256"] = hashlib.sha256((work/"bazel-bin/bytecode.h").read_bytes()).hexdigest()
    out.write_text(json.dumps(result, indent=2))
