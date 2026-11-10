"""Compare actual LuaJIT DynASM targets and integer operations on PowerPC."""
from pathlib import Path
from urllib.request import urlopen
import base64
import hashlib
import json
import os
import subprocess
import tempfile

base = 'a4f336eeac836d983cccce0167d321ca423acc91'
fixed = 'a4947b73f0040e460443984fd486483fa34f2830'
module = 'modules/luajit/2.1.1794214635'
out = Path(os.environ['RUNNER_TEMP']) / 'luajit-ppc-results.json'
result = {'before': base, 'after': fixed, 'cases': {}}
reg = Path.cwd()

def save():
    out.write_text(json.dumps(result, indent=2) + '\n')

def run(args, *, cwd=None, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    print('$', ' '.join(map(str,args)), '\n', (p.stdout + p.stderr)[-2800:], flush=True)
    if check:
        p.check_returncode()
    return p

save()
assert run(['git','rev-parse','HEAD^']).stdout.strip() == fixed
run(['git','fetch','--depth=1','https://github.com/tamird/bazel-central-registry.git',base])
module_text = '''module(name="consumer")
bazel_dep(name="luajit", version="2.1.1794214635")
bazel_dep(name="rules_cc", version="0.2.4")
bazel_dep(name="platforms", version="1.0.0")
cc_ext = use_extension("@rules_cc//cc:extensions.bzl", "cc_configure_extension")
use_repo(cc_ext, "local_config_cc")
'''
build_text = '''load("@rules_cc//cc:cc_binary.bzl", "cc_binary")
platform(name="ppc", constraint_values=["@platforms//cpu:ppc","@platforms//os:linux"])
toolchain(name="ppc_cc", toolchain="@local_config_cc//:cc-compiler-k8", toolchain_type="@bazel_tools//tools/cpp:toolchain_type", exec_compatible_with=["@platforms//cpu:ppc"], target_compatible_with=["@platforms//cpu:ppc"])
cc_binary(name="numbers", srcs=["numbers.c"], deps=["@luajit//:luajit"])
'''
consumer = r'''#include <stdio.h>
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
#include "lj_arch.h"
#if !LJ_TARGET_PPC || !LJ_DUALNUM || LJ_ARCH_BITS != 32 || !LJ_BE
#error expected a 32-bit big-endian PowerPC core with integer tags
#endif
int main(void) {
  printf("target=%s bits=%d dual=%d\n", LJ_ARCH_NAME, LJ_ARCH_BITS, LJ_DUALNUM);
  fflush(stdout);
  lua_State *s = luaL_newstate();
  if (!s) return 2;
  luaL_openlibs(s);
  if (luaL_dostring(s, "jit.off(); function numbers(a, b) return a+b, a<b end"))
    return 3;
  for (int i=0; i<2; i++) {
    lua_getglobal(s, "numbers");
    if (i == 0) { lua_pushinteger(s, 3); lua_pushinteger(s, 7); }
    else { lua_pushnumber(s, 3.25); lua_pushnumber(s, 7.25); }
    if (lua_pcall(s, 2, 2, 0)) { fprintf(stderr, "%s\n",lua_tostring(s,-1)); return 4; }
    double sum=lua_tonumber(s,-2); int less=lua_toboolean(s,-1);
    printf("%s sum=%g less=%d\n", i ? "fractional" : "integer", sum, less);
    if (sum != (i ? 10.5 : 10.0) || !less) return 5;
    lua_pop(s,2);
  }
  lua_close(s);
  return 0;
}
'''
with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as td:
    work = Path(td)
    bazel = work/'bazel'; bazel.write_bytes(urlopen('https://releases.bazel.build/9.3.1/release/bazel-9.3.1-linux-x86_64', timeout=90).read())
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(bazel)=='7f775b54bbec487efaf0f49ccda1d2ed02cd34f582edfdd6aeeec76e39ef585c'
    bazel.chmod(0o755)
    (work/'MODULE.bazel').write_text(module_text)
    (work/'BUILD.bazel').write_text(build_text)
    (work/'numbers.c').write_text(consumer)
    # Use a small local BCR index so Bazel loads the exact two public overlays.
    def set_registry(rev):
        r=work/rev; paths=['bazel_registry.json','modules/luajit/metadata.json',module+'/MODULE.bazel',module+'/source.json',module+'/overlay/BUILD.bazel',module+'/overlay/buildvm.bzl']
        for name in paths:
            f=r/name; f.parent.mkdir(parents=True,exist_ok=True)
            f.write_bytes(subprocess.check_output(['git','show',rev+':'+name],cwd=reg))
        meta=json.loads((r/module/'source.json').read_text())
        for name,integrity in meta['overlay'].items():
            assert 'sha256-'+base64.b64encode(hashlib.sha256((r/module/'overlay'/name).read_bytes()).digest()).decode() == integrity
        return ['--registry='+r.as_uri(),'--registry=https://bcr.bazel.build','--lockfile_mode=off','--color=no','--noshow_progress','--jobs=6']

    def bz(cmd, flags, *args, check=True):
        return run([str(bazel),'--nosystem_rc','--nohome_rc',cmd,*flags,*args],cwd=work,check=check)
    def outputs(flags, labels):
        p=bz('cquery',flags,'set('+' '.join(labels)+')','--output=files')
        return [work/line for line in p.stdout.splitlines() if line.startswith('bazel-out/')]
    headers=['@luajit//:'+name+'_arch_h' for name in ('buildvm','buildvm_linux_x64','buildvm_linux_x64_nogc64','buildvm_linux_arm64')]
    for rev in (base,fixed):
        flags=set_registry(rev)+['--platforms=//:ppc']
        bz('build',flags,*headers)
        files=outputs(flags, headers)
        assert len(files)==4
        hashes={f.parent.name:sha(f) for f in files}
        # aquery's default mnemonic depends on run_binary's target name.
        args=bz('aquery',flags,'@luajit//:buildvm_arch_h','--output=jsonproto')
        acts=json.loads(args.stdout)['actions']; argv=next(a['arguments'] for a in acts if any(v.endswith('dynasm/dynasm.lua') for v in a.get('arguments',[])))
        assert argv[-1].endswith('/vm_ppc.dasc') and ('DUALNUM' in argv)==(rev==fixed)
        result['cases'][rev]={'headerHashes':hashes,'ppcDynasmArguments':argv}
        save()
    before=result['cases'][base]['headerHashes']; after=result['cases'][fixed]['headerHashes']
    assert {k for k in before if before[k]!=after[k]}=={'buildvm'}
    # The C toolchain executes on AMD64 and emits genuine big-endian PPC32
    # programs. binfmt executes minilua/buildvm with the same ABI as the core.
    run(['sudo','apt-get','update','-qq'])
    run(['sudo','apt-get','install','-qq','-y','g++-powerpc-linux-gnu','qemu-user-static','binfmt-support'])
    run(['sudo','update-binfmts','--enable','qemu-ppc'])
    result['binfmt']=run(['cat','/proc/sys/fs/binfmt_misc/qemu-ppc']).stdout
    for rev in (base,fixed):
        flags=set_registry(rev)+['--platforms=//:ppc','--host_platform=//:ppc','--extra_toolchains=//:ppc_cc','--repo_env=CC=/usr/bin/powerpc-linux-gnu-gcc','--repo_env=AR=/usr/bin/powerpc-linux-gnu-ar','--action_env=QEMU_LD_PREFIX=/usr/powerpc-linux-gnu','--host_action_env=QEMU_LD_PREFIX=/usr/powerpc-linux-gnu']
        p=bz('build',flags,'//:numbers',check=False)
        rec=result['cases'][rev];rec['runtimeBuild']={'code':p.returncode,'diagnostic':(p.stderr+p.stdout)[-6000:]};save()
        if p.returncode:continue
        f,=outputs(flags,['//:numbers']);h=f.read_bytes()[:20]
        assert h[:6]==b'\x7fELF\x01\x02' and int.from_bytes(h[18:20],'big')==20
        p=run(['timeout','20','qemu-ppc-static','-L','/usr/powerpc-linux-gnu',str(f)],check=False)
        rec['runtime']={'elfSha256':sha(f),'class':'ELF32','data':'MSB','machine':20,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
        save()
    before=result['cases'][base].get('runtime',{}); after=result['cases'][fixed].get('runtime',{})
    assert before.get('exit') not in (None,0), before
    assert after.get('exit')==0 and 'integer sum=10 less=1' in after['stdout'] and 'fractional sum=10.5 less=1' in after['stdout'], after

