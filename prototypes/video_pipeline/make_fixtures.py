"""Generate finite synthetic H.264 fixtures OFFLINE using explicit software x264."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from encoding_decision import PROFILES
from sources import SPECS
from replay import access_units


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=2,choices=range(1,6))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);rows=[]
    for s in SPECS:
        for p in PROFILES:
            if p.width>s.width or p.height>s.height:continue
            name=f'{s.id}-{p.id}.h264';path=args.output/name
            command=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
                '-filter_threads','1','-f','lavfi','-i',f'testsrc2=size={p.width}x{p.height}:rate={p.fps}',
                '-vf',f'hue=h={s.hue},drawbox=x=0:y=0:w=iw:h=ih:color=0x{s.color[1:]}:t=12',
                '-t',str(args.seconds),'-an','-c:v','libx264','-pix_fmt','yuv420p','-threads','2',
                '-preset','ultrafast','-tune','zerolatency','-b:v',str(p.minimum_bps),
                '-minrate',str(p.minimum_bps),'-maxrate',str(p.minimum_bps),'-bufsize',str(p.minimum_bps),
                '-g',str(p.fps),'-bf','0','-x264-params','nal-hrd=cbr:scenecut=0:aud=1:repeat-headers=1',
                '-f','h264',str(path)]
            subprocess.run(command,check=True)
            data=path.read_bytes();frames=access_units(data)
            rows.append(dict(stream_id=s.id,profile_id=p.id,file=name,width=p.width,height=p.height,
                fps=p.fps,frames=len(frames),nominal_bitrate_bps=p.minimum_bps,
                file_average_bitrate_bps=len(data)*8*p.fps/len(frames),sha256=hashlib.sha256(data).hexdigest()))
            print(name,flush=True)
    (args.output/'manifest.json').write_text(json.dumps(dict(schema_version=1,mode='preencoded_software_test',
        fixtures=rows),indent=2)+'\n')


if __name__=='__main__':main()
