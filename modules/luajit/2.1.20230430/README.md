This dated version uses LuaJIT commit 224129a8e64bfa219d35cd03055bf03952f167f6
from 2023-04-30. The source still identifies itself as LuaJIT 2.1.0-beta3.

Linux x86_64 and ARM64 VM generators explicitly describe their output target,
while Bazel compiles and runs each generator on its execution platform. This
avoids producing host assembly for a different Linux target architecture.
Other native platform configurations retain their existing selection.

GC64 defaults to true, matching this upstream revision. Both the library and
its VM generator honor the gc64 build setting; the generator variant is
selected before its execution-platform transition. Generators use declared
executables directly without a host shell. COPYRIGHT and jit/bcsave.lua
are exported for packaging notices and embedding Lua bytecode, respectively.
