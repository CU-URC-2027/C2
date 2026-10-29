"""Build/probe a small native GStreamer worker without Python GI/ABI coupling.

Uses the native Homebrew prefix on Apple Silicon, and pkg-config on Linux.
All registry/plugin selection overrides are local to child processes.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
BINARY = ROOT/'artifacts/encoder-gst-worker'
SOURCE = ROOT/'native/encoder_worker.c'


def environment():
    if platform.system() not in ('Darwin','Linux'):
        raise RuntimeError('The native media worker requires POSIX macOS/Linux; native Windows is not supported')
    env = os.environ.copy()
    prefix = os.environ.get('VIDEO_LAB_GST_PREFIX')
    if not prefix and platform.system()=='Darwin' and platform.machine()=='arm64':
        prefix='/opt/homebrew/opt/gstreamer'
    if prefix:
        path=Path(prefix)
        if not path.exists():raise RuntimeError(f'Native GStreamer is unavailable at {path}')
        env['PKG_CONFIG_PATH']=str(path/'lib/pkgconfig')+os.pathsep+env.get('PKG_CONFIG_PATH','')
        # Do not scan unrelated old Intel plugins or modify global shell settings.
        plugins=ROOT/'artifacts/encoder-gst-plugins';plugins.mkdir(parents=True,exist_ok=True)
        names=('coreelements','app','applemedia','videoconvertscale','videorate','videoparsersbad','jpeg','libav')
        for name in names:
            source=path/'lib/gstreamer-1.0'/f'libgst{name}.dylib'
            if not source.exists():continue
            dest=plugins/source.name
            if dest.is_symlink() and dest.resolve()!=source.resolve():dest.unlink()
            if not dest.exists():dest.symlink_to(source)
        env['GST_PLUGIN_SYSTEM_PATH_1_0']=''
        env['GST_PLUGIN_PATH_1_0']=str(plugins)
        env['GST_PLUGIN_SCANNER']=str(path/'libexec/gstreamer-1.0/gst-plugin-scanner')
    env['GST_REGISTRY']=str(ROOT/'artifacts'/f'encoder-gst-registry-{platform.machine()}.bin')
    env['GST_DEBUG']='0'
    return env


def prepare():
    env=environment()
    pkg=shutil.which('pkg-config')
    if not pkg:raise RuntimeError('pkg-config and GStreamer development libraries are required')
    flags=subprocess.run([pkg,'--cflags','--libs','gstreamer-app-1.0','gstreamer-video-1.0'],
                         capture_output=True,text=True,env=env,timeout=10)
    if flags.returncode:raise RuntimeError('GStreamer development libraries unavailable: '+flags.stderr.strip())
    signature=hashlib.sha256(SOURCE.read_bytes()+flags.stdout.encode()).hexdigest()
    stamp=BINARY.with_suffix('.build')
    if not BINARY.exists() or not stamp.exists() or stamp.read_text()!=signature:
        BINARY.parent.mkdir(exist_ok=True)
        compiler=shutil.which('cc')
        if not compiler:raise RuntimeError('A C compiler is required for the native encoder worker')
        result=subprocess.run([compiler,'-std=c11','-O2','-Wall','-Wextra',str(SOURCE),'-o',str(BINARY),
                               *shlex.split(flags.stdout)],capture_output=True,text=True,env=env,timeout=30)
        if result.returncode:raise RuntimeError('Native encoder build failed: '+result.stderr[-3000:])
        stamp.write_text(signature)
    result=subprocess.run([str(BINARY),'--probe'],capture_output=True,text=True,env=env,timeout=10)
    if result.returncode:raise RuntimeError('Native encoder probe failed: '+result.stderr[-1000:])
    probe=json.loads(result.stdout)
    factory='vtenc_h264_hw' if platform.system()=='Darwin' else 'qsvh264enc'
    missing=[name for name in (factory,'appsrc','appsink','h264parse','videoscale','jpegenc') if not probe['factories'].get(name)]
    if missing:raise RuntimeError('Missing GStreamer factories: '+', '.join(missing))
    return {'binary':str(BINARY),'factory':factory,'environment':env,'probe':probe}


if __name__=='__main__':
    result=prepare()
    print(json.dumps({'binary':result['binary'],'factory':result['factory'],**result['probe']},indent=2))
