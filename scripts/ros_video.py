#!/usr/bin/env python3
"""Two-process ROS video prototype. HTTP stays loopback; remote media is explicit."""
import argparse
import ipaddress
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'prototypes/video_pipeline'))


def private_address(value):
    address=ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or not (address.is_private or address.is_loopback):
        raise argparse.ArgumentTypeError('Use an explicit private/loopback IPv4 address')
    return str(address)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=('c2','rover'))
    parser.add_argument('--peer',type=private_address,required=True)
    parser.add_argument('--bind',type=private_address)
    parser.add_argument('--namespace',default='/urc_video_lab')
    parser.add_argument('--port',type=int)
    parser.add_argument('--fixtures',type=Path)
    args=parser.parse_args()
    if args.role=='c2':
        if not args.bind:parser.error('C2 requires --bind for its private video receiver')
        from c2_web.runtime import Runtime
        from c2_web.video_ros import ROSVideoPriorities
        from c2_web.video_receiver import VideoReceiver
        from c2_web.api import create_app
        app=create_app(Runtime(video_priorities=ROSVideoPriorities(args.namespace)),
            VideoReceiver(port=8874,host=args.bind,allowed_peers=[args.peer]))
    else:
        from app import create_app
        from ros_status_runtime import ROSStatusRuntime
        from sources import SPECS
        status=ROSStatusRuntime([s.id for s in SPECS],args.namespace)
        factory=None;bank=None
        if args.fixtures:
            from replay import FixtureCatalog,ReplayBank,ReplayWorker
            from encoder_runtime import EncoderRuntime
            catalog=FixtureCatalog(args.fixtures);bank=ReplayBank(catalog)
            factory=lambda b,d:EncoderRuntime(b,d,worker_factory=ReplayWorker,
                native_prepare=lambda:catalog.native,execution_mode='preencoded_test')
        app=create_app(bank=bank,status_runtime=status,encoder_factory=factory,
            transmission_options=dict(allowed_hosts=[args.peer],host=args.peer))
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port or (8870 if args.role=='c2' else 8872),
        ws_max_size=550000,ws_per_message_deflate=False)


if __name__=='__main__':main()
