LuaJIT 2.1 uses the POSIX timestamp of the source commit as its release
number. This entry uses the timestamp recorded in the source archive and
LuaJIT's version-header generator.

The Linux x86_64 and ARM64 VM generators run on the execution platform.
Select the generator for the target architecture before Bazel builds it.
The gc64 setting selects the x86_64 frame layout and defaults to true.
Consumers can use the exported bytecode saver to embed Lua sources and
package the copyright notice with the VM.
